from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Access the variables
GEONAMES_USERNAME = os.getenv("GEONAMES_USERNAME", "demo")  # Fallback to "demo" if not set
OPENROUTE_API_KEY = os.getenv("OPENROUTE_API_KEY", "")
FLIGHTSTATS_APP_ID = os.getenv("FLIGHTSTATS_APP_ID", "")
FLIGHTSTATS_APP_KEY = os.getenv("FLIGHTSTATS_APP_KEY", "")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")



from supabase import create_client, Client

supabase: Client = create_client(
    supabase_url="https://dbvpdrikclcbemupgmjr.supabase.co",
    supabase_key="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRidnBkcmlrY2xjYmVtdXBnbWpyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDE5ODc2NDksImV4cCI6MjA1NzU2MzY0OX0.HyxtnWSSr-uEF47bRLQU68kPo3xxGUh8WuJDsOB3FU4"
)


from haystack.document_stores import InMemoryDocumentStore
from haystack.nodes import BM25Retriever
from haystack.schema import Document
from haystack import Pipeline
from haystack.pipelines import ExtractiveQAPipeline
import os
import json
import time
import requests
from datetime import datetime, timedelta
import logging
from typing import List, Dict, Optional
import re
import random
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    # Try to import optional components if available
    from haystack.nodes import FARMReader
    has_reader = True
except ImportError:
    has_reader = False



# Initialize document store
document_store = InMemoryDocumentStore(use_bm25=True)




class SupabaseService:
    def __init__(self, url, key):
        self.supabase = create_client(url, key)
        # Create tables in Supabase (SQL):
        """
        create table trips (
            id serial primary key,
            user_id text,
            destination text,
            start_date date,
            end_date date,
            itinerary text
        );

        create table query_history (
            id serial primary key,
            user_id text,
            query text,
            response text,
            timestamp timestamptz
        );
        """
        
    def store_trip_data(self, user_id, trip_data):
        try:
            result = self.supabase.table('trips').insert({
                # data
            }).execute()
            if not result.data:
                logger.error("Supabase insert failed")
            return result
        except Exception as e:
            logger.error(f"Supabase error: {str(e)}")
            return None
        
    def get_user_trips(self, user_id):
        return self.supabase.table('trips').select('*').eq('user_id', user_id).execute()
        
    def store_query_history(self, user_id, query, response):
        return self.supabase.table('query_history').insert({
            'user_id': user_id,
            'query': query,
            'response': response,
            'timestamp': datetime.now().isoformat()
        }).execute()

class LocationService:
    """Service for fetching location data from Geonames and other sources"""
    
    def __init__(self, username=GEONAMES_USERNAME):
        self.username = username
        logger.info(f"LocationService initialized with username: {self.username}")
        
    def get_nearby_places(self, lat, lng, radius=10, max_rows=10, feature_class="P"):
        """
        Get nearby places using Geonames API
        
        Args:
            lat (float): Latitude of the center point
            lng (float): Longitude of the center point
            radius (int): Search radius in kilometers
            max_rows (int): Maximum number of results
            feature_class (str): Geonames feature class (e.g., 'P' for populated places)
            
        Returns:
            list: List of nearby places
        """
        logger.info(f"Searching nearby places around ({lat}, {lng})")
        
        # Fallback data for popular destinations
        fallback_nearby = {
            "paris": [
                {"name": "Eiffel Tower", "lat": 48.8584, "lng": 2.2945, "type": "Tourist Attraction"},
                {"name": "Louvre Museum", "lat": 48.8606, "lng": 2.3376, "type": "Museum"},
                {"name": "Notre-Dame Cathedral", "lat": 48.8530, "lng": 2.3499, "type": "Religious Site"}
            ],
            "new york": [
                {"name": "Statue of Liberty", "lat": 40.6892, "lng": -74.0445, "type": "Monument"},
                {"name": "Central Park", "lat": 40.7851, "lng": -73.9683, "type": "Park"},
                {"name": "Times Square", "lat": 40.7580, "lng": -73.9855, "type": "Square"}
            ],
            # Add more fallback data as needed
        }
        
        try:
            url = "http://api.geonames.org/findNearbyPlaceNameJSON"
            params = {
                "lat": lat,
                "lng": lng,
                "radius": radius,
                "maxRows": max_rows,
                "username": self.username,
                "featureClass": feature_class
            }
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            nearby_places = []
            for place in data.get("geonames", []):
                nearby_places.append({
                    "name": place.get("name", "Unnamed Place"),
                    "lat": place.get("lat"),
                    "lng": place.get("lng"),
                    "type": place.get("fcode", ""),
                    "country": place.get("countryName", "")
                })
            
            if nearby_places:
                return nearby_places[:max_rows]
            
            # Fallback to check major cities
            for city in fallback_nearby:
                city_data = self.search_destinations(city, max_rows=1)
                if city_data and abs(city_data[0]["lat"] - lat) < 1 and abs(city_data[0]["lng"] - lng) < 1:
                    return fallback_nearby[city]
            
            return []
            
        except Exception as e:
            logger.error(f"Error fetching nearby places: {str(e)}")
            # Try to find matching fallback data
            for city in fallback_nearby:
                city_data = self.search_destinations(city, max_rows=1)
                if city_data and abs(city_data[0]["lat"] - lat) < 1 and abs(city_data[0]["lng"] - lng) < 1:
                    return fallback_nearby[city]
            return []
    
    def get_country_info(self, country_name):
        """Get basic country information from Geonames"""
        logger.info(f"Fetching country info for: {country_name}")
        
        # Fallback data for common countries
        fallback_countries = {
            "France": {
                "continentName": "Europe",
                "population": 67390000,
                "capital": "Paris",
                "currencyCode": "EUR"
            },
            "United States": {
                "continentName": "North America",
                "population": 331900000,
                "capital": "Washington, D.C.",
                "currencyCode": "USD"
            },
            "China": {
                "continentName": "Asia",
                "population": 1409670000,
                "capital": "Beijing",
                "currencyCode": "CNY"
            },
            "Japan": {
                "continentName": "Asia",
                "population": 125700000,
                "capital": "Tokyo",
                "currencyCode": "JPY"
            },
            "Thailand": {
                "continentName": "Asia", 
                "population": 71800000,
                "capital": "Bangkok",
                "currencyCode": "THB"
            },
            "Australia": {
                "continentName": "Oceania",
                "population": 25690000,
                "capital": "Canberra",
                "currencyCode": "AUD"
            }
        }
        
        try:
            url = "http://api.geonames.org/countryInfoJSON"
            params = {
                "country": country_name,
                "username": self.username
            }
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get("geonames"):
                country_data = data["geonames"][0]
                return {
                    "continentName": country_data.get("continentName", ""),
                    "population": int(country_data.get("population", 0)),
                    "capital": country_data.get("capital", ""),
                    "currencyCode": country_data.get("currencyCode", "")
                }
            
        except Exception as e:
            logger.error(f"Error fetching country info: {str(e)}")
        
        # Fallback to hardcoded data
        for name, data in fallback_countries.items():
            if name.lower() == country_name.lower():
                return data
        
        # Default return if no match found
        return {
            "continentName": "Unknown",
            "population": 0,
            "capital": "Unknown",
            "currencyCode": ""
        }

    def search_destinations(self, query, max_rows=10, feature_class="P", feature_code=None):
        """Search for destinations using Geonames API."""
        # Add country/state filtering
        original_query = query
        country_filter = None
        
        # Extract country/state from query
        if ',' in query:
            parts = [p.strip() for p in query.split(',')]
            query = parts[0]
            country_filter = parts[-1].lower()
        
        logger.info(f"Searching destinations for: {query}")
        
        try:
            # API request parameters
            url = "http://api.geonames.org/searchJSON"
            params = {
                "q": query,
                "maxRows": max_rows,
                "username": self.username,
                "style": "FULL",
                "isNameRequired": "true",
                "featureClass": feature_class,
                "orderby": "relevance"
            }
            
            # Add feature code if specified
            if feature_code:
                params["featureCode"] = feature_code
                
            # Make API request
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Process results
            destinations = []
            for place in data.get("geonames", []):
                # Filter for populated places (PPLC = capital, PPL = city)
                if place.get("fcode", "").startswith("PP"):
                    dest = {
                        "name": place.get("name", ""),
                        "country": place.get("countryName", ""),
                        "country_code": place.get("countryCode", ""),
                        "population": place.get("population", 0),
                        "lat": float(place.get("lat", 0)),
                        "lng": float(place.get("lng", 0)),
                        "timezone": place.get("timezone", {}).get("timeZoneId", ""),
                        "feature_code": place.get("fcode", ""),
                        "admin_region": place.get("adminName1", "")
                    }
                    destinations.append(dest)
            
            # Sort by population (largest cities first)
            destinations.sort(key=lambda x: x["population"], reverse=True)
            
            # Post-filter results
            if country_filter:
                filtered = []
                for dest in destinations:
                    if country_filter in dest['country'].lower() or \
                    country_filter in dest['admin_region'].lower():
                        filtered.append(dest)
                destinations = filtered
            
            # Only use fallback if we have no results at all
            if not destinations:
                logger.warning(f"No results found for {original_query}, trying fallback")
                fallback_results = self._fallback_search(original_query, max_rows)
                if fallback_results:
                    logger.info(f"Using fallback data for {original_query}")
                    return fallback_results
            
            return destinations[:max_rows]
            
        except Exception as e:
            logger.error(f"GeoNames API error: {str(e)}")
            # Only use fallback if API call fails
            return self._fallback_search(query, max_rows)

    def _fallback_search(self, query, max_rows):
        """Fallback search when Geonames API fails."""
        logger.info(f"Using local fallback data for: {query}")
        
        # Fallback data for popular destinations
        fallback_data = {
            "hong kong": {
                "name": "Hong Kong",
                "country": "China",
                "country_code": "HK",
                "population": 7482500,
                "lat": 22.3193,
                "lng": 114.1694,
            },
            "paris": {
                "name": "Paris",
                "country": "France",
                "country_code": "FR",
                "population": 2140526,
                "lat": 48.8566,
                "lng": 2.3522,
            },
            "new york": {
                "name": "New York",
                "country": "United States",
                "country_code": "US",
                "population": 8804190,
                "lat": 40.7128,
                "lng": -74.0060,
            },
            "tokyo": {
                "name": "Tokyo",
                "country": "Japan",
                "country_code": "JP",
                "population": 13960000,
                "lat": 35.6762,
                "lng": 139.6503,
            },
            "london": {
                "name": "London",
                "country": "United Kingdom",
                "country_code": "GB",
                "population": 8982000,
                "lat": 51.5074,
                "lng": -0.1278,
            },
            "rome": {
                "name": "Rome",
                "country": "Italy",
                "country_code": "IT",
                "population": 2873000,
                "lat": 41.9028,
                "lng": 12.4964,
            },
            "sydney": {
                "name": "Sydney",
                "country": "Australia",
                "country_code": "AU",
                "population": 5312000,
                "lat": -33.8688,
                "lng": 151.2093,
            },
            "bangkok": {
                "name": "Bangkok",
                "country": "Thailand",
                "country_code": "TH",
                "population": 8281000,
                "lat": 13.7563,
                "lng": 100.5018,
            }
        }
        
        query_lower = query.lower()
        results = []
        
        # Exact match first
        if query_lower in fallback_data:
            return [fallback_data[query_lower]]
            
        # Partial matches - only if no exact match
        for key, data in fallback_data.items():
            # Check if query is part of the key or if any word in query is in key
            if query_lower in key or any(word in key for word in query_lower.split()):
                results.append(data)
                if len(results) >= max_rows:
                    break
        
        # If we still have no results, check if any city name contains the query
        if not results:
            for key, data in fallback_data.items():
                if query_lower in data["name"].lower():
                    results.append(data)
                    if len(results) >= max_rows:
                        break
                    
        return results
            



class RouteService:
    """Service for calculating routes and directions using OpenRoute Service"""
    
    def __init__(self, api_key=OPENROUTE_API_KEY):
        self.api_key = api_key
        self.base_url = "https://api.openrouteservice.org"
    
    def geocode(self, query):
        """Geocode a location using Nominatim"""
        try:
            url = "https://nominatim.openstreetmap.org/search"
            params = {
                "q": query,
                "format": "json",
                "limit": 1
            }
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            results = response.json()
            
            if results:
                return {
                    "name": results[0].get("display_name", ""),
                    "lat": float(results[0].get("lat", 0)),
                    "lng": float(results[0].get("lon", 0)),
                    "osm_id": results[0].get("osm_id")
                }
            return None
        except Exception as e:
            logger.error(f"Error geocoding location: {str(e)}")
            return None
    
    def get_directions(self, start_point, end_point, profile="foot-walking"):
        """
        Get directions between two points
        
        Args:
            start_point (tuple): Starting point (lng, lat)
            end_point (tuple): Ending point (lng, lat)
            profile (str): Travel profile (foot-walking, cycling-regular, driving-car)
            
        Returns:
            dict: Route information
        """
        if not self.api_key:
            logger.warning("OpenRoute API key not provided, returning simplified directions")
            return {
                "distance": 0,
                "duration": 0,
                "route": [start_point, end_point]
            }
            
        try:
            url = f"{self.base_url}/v2/directions/{profile}"
            headers = {
                "Authorization": self.api_key,
                "Content-Type": "application/json"
            }
            
            data = {
                "coordinates": [start_point, end_point]
            }
            
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            
            # Extract relevant information
            if "routes" in result and result["routes"]:
                route = result["routes"][0]
                return {
                    "distance": route.get("summary", {}).get("distance", 0),
                    "duration": route.get("summary", {}).get("duration", 0),
                    "geometry": route.get("geometry")
                }
            return None
        except Exception as e:
            logger.error(f"Error getting directions: {str(e)}")
            return None
    
    def get_places_of_interest(self, center_point, radius=2000, categories=None):
        """
        Find places of interest around a location using OpenRoute POI service
        
        Args:
            center_point (tuple): Center point (lng, lat)
            radius (int): Search radius in meters
            categories (list): POI categories to include
            
        Returns:
            list: Places of interest
        """
        if not self.api_key:
            logger.warning("OpenRoute API key not provided, cannot fetch places of interest")
            return []
            
        try:
            url = f"{self.base_url}/pois"
            headers = {
                "Authorization": self.api_key,
                "Content-Type": "application/json"
            }
            
            data = {
                "request": "pois",
                "geometry": {
                    "buffer": radius,
                    "geojson": {
                        "type": "Point",
                        "coordinates": center_point
                    }
                }
            }
            
            if categories:
                data["filters"] = {
                    "category_ids": categories
                }
            
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            
            pois = []
            for feature in result.get("features", []):
                props = feature.get("properties", {})
                coords = feature.get("geometry", {}).get("coordinates", [])
                
                poi = {
                    "name": props.get("name", "Unknown"),
                    "category": props.get("category_name", ""),
                    "lng": coords[0] if len(coords) > 0 else 0,
                    "lat": coords[1] if len(coords) > 1 else 0,
                    "osm_id": props.get("osm_id", "")
                }
                pois.append(poi)
                
            return pois
        except Exception as e:
            logger.error(f"Error getting places of interest: {str(e)}")
            return []


class FlightService:
    """Service for fetching flight information using FlightStats API"""
    
    def __init__(self, app_id=FLIGHTSTATS_APP_ID, app_key=FLIGHTSTATS_APP_KEY):
        self.app_id = app_id
        self.app_key = app_key
        self.base_url = "https://api.flightstats.com/flex"
    
    def search_airports(self, query):
        """Search for airports by name or city"""
        if not (self.app_id and self.app_key):
            logger.warning("FlightStats credentials not provided, returning simulated airport data")
            # Return some simulated data for demo purposes
            if "new york" in query.lower():
                return [{"code": "JFK", "name": "John F. Kennedy International Airport", "city": "New York"}]
            elif "tokyo" in query.lower():
                return [{"code": "NRT", "name": "Narita International Airport", "city": "Tokyo"}]
            elif "london" in query.lower():
                return [{"code": "LHR", "name": "Heathrow Airport", "city": "London"}]
            elif "paris" in query.lower():
                return [{"code": "CDG", "name": "Charles de Gaulle Airport", "city": "Paris"}]
            else:
                return []
                
        try:
            url = f"{self.base_url}/airports/rest/v1/json/search/{query}"
            params = {
                "appId": self.app_id,
                "appKey": self.app_key
            }
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            airports = []
            for airport in data.get("airports", []):
                airports.append({
                    "code": airport.get("fs", ""),
                    "name": airport.get("name", ""),
                    "city": airport.get("city", ""),
                    "country": airport.get("countryName", ""),
                    "lat": airport.get("latitude", 0),
                    "lng": airport.get("longitude", 0)
                })
            
            return airports
        except Exception as e:
            logger.error(f"Error searching airports: {str(e)}")
            return []
    
    def get_flights(self, departure_airport, arrival_airport, date):
        """Get flights between two airports on a specific date"""
        if not (self.app_id and self.app_key):
            logger.warning("FlightStats credentials not provided, returning simulated flight data")
            # Generate simulated flight data
            flight_time = 2.5  # hours
            if "JFK" in (departure_airport, arrival_airport) and "LHR" in (departure_airport, arrival_airport):
                flight_time = 7.5
            elif "JFK" in (departure_airport, arrival_airport) and "CDG" in (departure_airport, arrival_airport):
                flight_time = 7.0
            elif "NRT" in (departure_airport, arrival_airport) and "JFK" in (departure_airport, arrival_airport):
                flight_time = 14.0
                
            flights = []
            airlines = ["AA", "UA", "DL", "BA", "LH", "AF", "JL", "NH"]
            flight_numbers = ["101", "202", "303", "404", "505", "606", "707", "808"]
            
            # Generate a few simulated flights
            for i in range(3):
                departure_time = datetime.now() + timedelta(days=1, hours=i*3)
                arrival_time = departure_time + timedelta(hours=flight_time)
                
                flights.append({
                    "carrier": airlines[i % len(airlines)],
                    "flight_number": flight_numbers[i % len(flight_numbers)],
                    "departure": {
                        "airport": departure_airport,
                        "time": departure_time.strftime("%Y-%m-%dT%H:%M:%S")
                    },
                    "arrival": {
                        "airport": arrival_airport,
                        "time": arrival_time.strftime("%Y-%m-%dT%H:%M:%S")
                    },
                    "duration": int(flight_time * 60),  # minutes
                    "status": "Scheduled"
                })
                
            return flights
                
        try:
            # Format date as YYYY/MM/DD
            formatted_date = date.strftime("%Y/%m/%d") if isinstance(date, datetime) else date
            
            url = f"{self.base_url}/schedules/rest/v1/json/from/{departure_airport}/to/{arrival_airport}/departing/{formatted_date}"
            params = {
                "appId": self.app_id,
                "appKey": self.app_key
            }
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            flights = []
            for flight in data.get("scheduledFlights", []):
                departure_time = flight.get("departureTime", "")
                arrival_time = flight.get("arrivalTime", "")
                
                flights.append({
                    "carrier": flight.get("carrierFsCode", ""),
                    "flight_number": flight.get("flightNumber", ""),
                    "departure": {
                        "airport": departure_airport,
                        "terminal": flight.get("departureTerminal", ""),
                        "time": departure_time
                    },
                    "arrival": {
                        "airport": arrival_airport,
                        "terminal": flight.get("arrivalTerminal", ""),
                        "time": arrival_time
                    },
                    "duration": flight.get("flightDurationMinutes", 0),
                    "aircraft": flight.get("aircraft", {}).get("name", "")
                })
            
            return flights
        except Exception as e:
            logger.error(f"Error getting flights: {str(e)}")
            return []


class WeatherService:
    """Service for fetching weather information"""
    
    def __init__(self, api_key=WEATHER_API_KEY):
        self.api_key = api_key
    
    def get_forecast(self, lat, lng, days=7):
        """Get weather forecast for a location"""
        if not self.api_key:
            logger.warning("Weather API key not provided, returning simulated weather data")
            # Return simulated data
            forecast = []
            base_temp = 22  # Base temperature in Celsius
            for i in range(days):
                # Simple variation
                temp = base_temp + (-2 + (i % 5))
                temp_min = temp - 5
                temp_max = temp + 5
                
                # Alternate between sunny and cloudy
                conditions = "Sunny" if i % 3 == 0 else "Partly Cloudy" if i % 3 == 1 else "Cloudy"
                
                forecast.append({
                    "date": (datetime.now() + timedelta(days=i)).strftime("%Y-%m-%d"),
                    "temp": temp,
                    "temp_min": temp_min,
                    "temp_max": temp_max,
                    "conditions": conditions,
                    "precipitation_probability": 10 if conditions == "Sunny" else 30 if conditions == "Partly Cloudy" else 60
                })
                
            return forecast
                
        try:
            url = "https://api.openweathermap.org/data/2.5/onecall"
            params = {
                "lat": lat,
                "lon": lng,
                "exclude": "current,minutely,hourly,alerts",
                "units": "metric",
                "appid": self.api_key
            }
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            forecast = []
            for day in data.get("daily", [])[:days]:
                date = datetime.fromtimestamp(day.get("dt", 0)).strftime("%Y-%m-%d")
                
                forecast.append({
                    "date": date,
                    "temp": day.get("temp", {}).get("day", 0),
                    "temp_min": day.get("temp", {}).get("min", 0),
                    "temp_max": day.get("temp", {}).get("max", 0),
                    "conditions": day.get("weather", [{}])[0].get("main", ""),
                    "description": day.get("weather", [{}])[0].get("description", ""),
                    "precipitation_probability": day.get("pop", 0) * 100
                })
            
            return forecast
        except Exception as e:
            logger.error(f"Error getting weather forecast: {str(e)}")
            return []


# Initialize document store with explicit parameters
document_store = InMemoryDocumentStore(use_bm25=True, similarity="cosine")




# Response templates with proper randomization
class ResponseTemplates:
    def __init__(self):
        self.destinations = [
            "Here are some great options matching your search:",
            "Based on your preferences, I recommend:",
            "You might enjoy these destinations:",
            "I found these perfect locations for you:",
            "Top picks for your travel plans:"
        ]
        
        self.budget = [
            "With your ${budget} budget, consider these options:",
            "Here are destinations that fit your ${budget} budget:",
            "Great choices within your ${budget} range:"
        ]
        
        self.itinerary = [
            "Let's plan your perfect trip to {destination}:",
            "Here's your customized {days}-day itinerary:",
            "Your adventure in {destination} awaits:"
        ]

    def get_destination_template(self) -> str:
        return random.choice(self.destinations)
    
    def get_budget_template(self, budget: int) -> str:
        template = random.choice(self.budget)
        return template.replace("{budget}", str(budget))
    
    def get_itinerary_template(self, destination: str, days: int) -> str:
        template = random.choice(self.itinerary)
        return template.replace("{destination}", destination).replace("{days}", str(days))

class TripPlanner:
    """Main class for planning trips and generating itineraries"""
    
    def __init__(self):
        self.location_service = LocationService(username="curiousclump")  # Add your username here
        self.route_service = RouteService()
        self.flight_service = FlightService()
        self.weather_service = WeatherService()
        self.document_store = document_store
        self.templates = ResponseTemplates()
        
        # Initialize retriever after documents are loaded to ensure index exists
        self.search_pipeline = None
        self.retriever = None
        
        # Add a reader if available (for more advanced question answering)
        self.reader = None
        if has_reader:
            try:
                # First check if sentence_transformers is available
                try:
                    import sentence_transformers
                    self.reader = FARMReader(model_name_or_path="deepset/roberta-base-squad2", use_gpu=False)
                    logger.info("Reader successfully initialized.")
                except ImportError:
                    logger.warning("Missing dependency: sentence_transformers. Run 'pip install sentence_transformers'.")
                    logger.info("Running with retriever only mode.")
            except Exception as e:
                logger.error(f"Reader could not be initialized due to: {e}")
                logger.info("Running with retriever only mode.")
        
        # Load destination data
        self.update_destination_data()
        
        # Initialize retriever and pipeline after documents are loaded
        self.retriever = BM25Retriever(document_store=self.document_store)
        
        # Create a search pipeline
        self.search_pipeline = Pipeline()
        self.search_pipeline.add_node(component=self.retriever, name="Retriever", inputs=["Query"])
        
        # Add reader to pipeline if available
        if self.reader:
            self.search_pipeline.add_node(component=self.reader, name="Reader", inputs=["Retriever"])

    def _show_destination_details(self, last_response):
        """Show detailed information about the first recommended destination from the last response."""
        # Extract the first destination from the last response
        match = re.search(r"Option 1: ([\w\s]+), ([\w\s]+)", last_response)
        if not match:
            return "I couldn't find destination details from our previous conversation. Could you specify which destination you're interested in?"
        
        destination_name = match.group(1).strip()
        country_name = match.group(2).strip()
        
        # Generate a detailed itinerary for this destination
        return self.generate_itinerary(destination_name, days=3)

    def _expand_itinerary(self, last_response):
        """Expand the itinerary with more details."""
        # Extract the destination from the last response
        match = re.search(r"Itinerary for ([\w\s]+),", last_response)
        if not match:
            return "I couldn't find the destination from our previous conversation. Could you specify which destination you'd like more details about?"
        
        destination_name = match.group(1).strip()
        
        # Generate a more detailed itinerary with more days
        return self.generate_itinerary(destination_name, days=5) + "\n\nI've expanded the itinerary to 5 days with more detailed activities and recommendations."
    
    def update_destination_data(self):
        """Update destination data in the document store with popular destinations"""
        popular_locations = ["Paris", "New York", "Tokyo", "London", "Rome", "Iceland", "Bangkok", "Sydney"]
        
        for location in popular_locations:
            if ',' in location:
                city, state = [x.strip() for x in location.split(',')]
                content = f"{city}, {state}: A popular destination in {state} state."
                metadata = {
                    "name": city,
                    "state": state,
                    "country": "United States",
                    "region": "Midwest" if "Ohio" in state else "Northeast"  # etc.
                }
        
        docs = []
        for location in popular_locations:
            # Search for the location
            destinations = self.location_service.search_destinations(location, max_rows=1)
            if not destinations:
                continue
                
            dest = destinations[0]
            
            # Get nearby places
            nearby = self.location_service.get_nearby_places(
                dest["lat"], dest["lng"], radius=5, max_rows=5
            )
            
            # Create activities based on nearby places
            activities = []
            for place in nearby:
                if place.get("name") != dest["name"]:
                    activities.append(f"Visit {place.get('name')}")
            
            # Add some generic activities
            generic_activities = [
                f"Explore the city center of {dest['name']}",
                f"Try local cuisine in {dest['name']}",
                f"Shop at local markets",
                f"Visit museums and galleries",
                f"Take a guided city tour"
            ]
            
            # Combine and limit activities
            activities = activities + generic_activities
            activities = activities[:6]  # Limit to 6 activities
            
            # Create document content
            content = f"{dest['name']}, {dest['country']}: A vibrant destination with a population of approximately {dest['population']}. " \
                     f"Activities include: {', '.join(activities)}."
                     
            # Create metadata
            metadata = {
                "name": dest["name"],
                "country": dest["country"],
                "lat": dest["lat"],
                "lng": dest["lng"],
                "population": dest["population"],
                "activities": activities,
                "tags": ["city", "tourism", "travel"]
            }
            
            docs.append(Document(content=content, meta=metadata))
        
        # Ensure there are at least some documents even if API calls fail
        if not docs:
            fallback_destinations = popular_locations if popular_locations else ["Paris", "New York", "Tokyo"]
            for location in fallback_destinations:
                content = f"{location}: Popular destination with various attractions."
                metadata = {
                    "name": location,
                    "country": "Unknown",
                    "budget_level": "moderate",
                    "tags": ["city", "tourism"]
                }
                docs.append(Document(content=content, meta=metadata))
        
        # Write documents to the document store
        if docs:
            try:
                # Clear existing documents to avoid duplicates
                self.document_store.delete_documents()  # Updated method
                
                # Write new documents
                self.document_store.write_documents(docs)
                
                # Update embeddings if the retriever supports it
                if hasattr(self.retriever, "embed_documents"):
                    self.document_store.update_embeddings(self.retriever)
                
                logger.info(f"Updated document store with {len(docs)} destinations")
            except Exception as e:
                logger.error(f"Error updating document store: {e}")
                # If writing fails, try without deleting first
                try:
                    self.document_store.write_documents(docs)
                    logger.info(f"Updated document store with {len(docs)} destinations (without prior deletion)")
                except Exception as e2:
                    logger.error(f"Error writing documents to store: {e2}")
    
    def search_destinations(self, query, top_k=3):
        """Search for destinations based on user query"""
        # First try to search directly from Geonames
        destinations = self.location_service.search_destinations(query, max_rows=top_k)

        unique_destinations = []
        seen = set()
        for dest in destinations:
            key = (dest["name"], dest["country"])
            if key not in seen:
                seen.add(key)
                unique_destinations.append(dest)
    
        
        
        # If no results or too few, also search the document store
        if len(destinations) < top_k and self.search_pipeline:
            try:
                results = self.search_pipeline.run(query=query, params={"Retriever": {"top_k": top_k - len(destinations)}})
                
                for doc in results["documents"]:
                    # Skip if already in destinations
                    if any(d["name"] == doc.meta["name"] for d in destinations):
                        continue
                        
                    dest = {
                        "name": doc.meta["name"],
                        "country": doc.meta.get("country", "Unknown"),
                        "lat": doc.meta.get("lat", 0),
                        "lng": doc.meta.get("lng", 0),
                        "population": doc.meta.get("population", 0),
                        "activities": doc.meta.get("activities", [])
                    }
                    destinations.append(dest)
            except Exception as e:
                logger.error(f"Error searching document store: {e}")
                # Fall back to the destinations we already have
        
        return destinations[:top_k] if destinations else []
    
    def generate_itinerary(self, destination, days=3):
        """Generate a day-by-day itinerary for a destination"""
        # Extract name and country if a destination object is provided
        if isinstance(destination, dict):
            dest_name = destination.get("name", "")
            dest_country = destination.get("country", "")
            dest_lat = destination.get("lat", 0)
            dest_lng = destination.get("lng", 0)
        else:
            # Search for the destination if only a name is provided
            destinations = self.location_service.search_destinations(destination, max_rows=1)
            if not destinations:
                return f"Could not generate itinerary for {destination}. Destination not found in database."
                
            dest = destinations[0]
            dest_name = dest["name"]
            dest_country = dest["country"]
            dest_lat = dest["lat"]
            dest_lng = dest["lng"]
        
        # Get weather forecast if possible
        weather = self.weather_service.get_forecast(dest_lat, dest_lng, days=days)
        
        # Get points of interest
        pois = self.route_service.get_places_of_interest((dest_lng, dest_lat), radius=10000)
        
        # If no POIs from API, use default activities or search nearby places
        activities = []
        if pois:
            for poi in pois:
                activities.append(f"Visit {poi['name']}")
        else:
            # Try to get nearby places from Geonames
            nearby = self.location_service.get_nearby_places(dest_lat, dest_lng, radius=10, max_rows=10)
            for place in nearby:
                activities.append(f"Visit {place.get('name')}")
                
            # Add some generic activities
            generic_activities = [
                f"Explore the city center of {dest_name}",
                f"Try local cuisine in {dest_name}",
                f"Shop at local markets",
                f"Visit museums and galleries",
                f"Take a guided city tour",
                f"Relax in a local park",
                f"Experience the nightlife",
                f"Join a walking tour"
            ]
            activities.extend(generic_activities)
        
        # Ensure we have enough activities
        if len(activities) < days * 3:
            activities = activities * ((days * 3) // len(activities) + 1)
        
        # Generate the itinerary
        itinerary = f"\n{days}-Day Itinerary for {dest_name}, {dest_country}:\n"
        
        # Distribute activities across days
        activities_per_day = max(1, min(len(activities) // days, 5))  # At most 5 activities per day
        
        for day in range(1, days + 1):
            day_weather = None
            if weather and day <= len(weather):
                day_weather = weather[day-1]
                
            itinerary += f"\nDay {day}"
            
            if day_weather:
                itinerary += f" - Weather: {day_weather['conditions']}, {day_weather['temp_min']}°C to {day_weather['temp_max']}°C"
                
            itinerary += ":\n"
            
            start_idx = (day - 1) * activities_per_day
            end_idx = min(start_idx + activities_per_day, len(activities))
            
            if day == days:  # Last day gets any remaining high-priority activities
                end_idx = min(start_idx + activities_per_day, len(activities))
            
            # Morning
            itinerary += "Morning:\n"
            if start_idx < end_idx:
                itinerary += f"- {activities[start_idx]}\n"
                
            # Adjust morning activities based on weather
            if day_weather and day_weather['conditions'] == "Sunny":
                itinerary += "- Enjoy breakfast at an outdoor café\n"
            else:
                itinerary += "- Breakfast at a local café\n"
            
            # afternoon
            itinerary += "\nAfternoon:\n"
            for i in range(start_idx + 1, min(start_idx + 3, end_idx)):
                itinerary += f"- {activities[i]}\n"
                
            # Adjust aFternoon activities based on weather
            if day_weather and day_weather['precipitation_probability'] > 50:
                itinerary += "- Visit indoor attractions due to possible rain\n"
            
            itinerary += "- Lunch at a recommended restaurant\n"
            
            # Evening
            itinerary += "\nEvening:\n"
            if start_idx + 3 < end_idx:
                itinerary += f"- {activities[start_idx + 3]}\n"
                
            itinerary += "- Dinner at a local restaurant\n"
            
            if day == 1:
                itinerary += "- Evening stroll to get oriented with the area\n"
            elif day == days:
                itinerary += "- Farewell dinner with local specialties\n"
            else:
                itinerary += "- Relax and enjoy local entertainment\n"
        
        # Add travel tips
        itinerary += f"\nTravel Tips for {dest_name}:\n"
        
        # Best time to visit based on hemisphere and typical seasons
        if dest_lat > 0:  # Northern Hemisphere
            itinerary += "- Best time to visit: Spring (April-June) and Fall (September-October)\n"
        else:  # Southern Hemisphere
            itinerary += "- Best time to visit: Spring (September-November) and Fall (March-May)\n"
            
        # Budget estimate based on country
        if dest_country:
            country_info = self.location_service.get_country_info(dest_country)
            continent = country_info.get("continentName", "")
            
            budget_estimation = ""
            if continent:
                if continent in ["Europe", "North America", "Australia"]:
                    budget_estimation = "Medium to High"
                elif dest_name in ["Tokyo", "Singapore", "Hong Kong", "Dubai"]:
                    budget_estimation = "High"
                else:
                    budget_estimation = "Low to Medium"
        
        if budget_estimation:
            itinerary += f"- Budget range: {budget_estimation}\n"
        
        itinerary += "- Remember to research local customs and etiquette\n"
        itinerary += "- Check for any required travel documents or vaccinations\n"
        
        # Transportation tips
        if country_info:
            if country_info.get("population", 0) > 50000000:  # Larger countries
                itinerary += "- Consider internal flights for longer distances\n"
            
        itinerary += "- Research public transportation options\n"
        
        return itinerary
    

    
    def plan_trip(self, query: str) -> str:
        """
        Create a trip plan based on user query.

        Args:
            query (str): The user's travel-related query.

        Returns:
            str: A formatted response with destination recommendations.
        """
        # Log the query
        logger.info(f"Searching for destinations based on query: {query}")
        
        # Extract budget if present
        budget = self.extract_budget(query)
        
        # Get template for the response
        if budget:
            template = f"With your ${budget} budget, consider these options:"
        else:
            template = random.choice(self.RESPONSE_TEMPLATES['destinations'])
        
        response = f"{template}\n\n"
        
        # Search for destinations
        destinations = self.search_destinations(query)
        
        # Handle no results case
        if not destinations:
            no_results_templates = [
                "I couldn't find any destinations matching your search. Could you provide more details?",
                "No results found. Try being more specific about your destination.",
                "Hmm, I'm not finding anything. Maybe try a different location?"
            ]
            return random.choice(no_results_templates)
        
        # Build destination list
        for i, dest in enumerate(destinations, 1):
            response += f"Option {i}: {dest['name']}, {dest['country']}\n"
            
            # Add nearby attractions if available
            nearby = self._get_nearby_attractions(dest)
            if nearby:
                response += f"  - Nearby attractions: {', '.join(nearby)}\n"
            
            # Add population info if available
            if dest.get("population", 0) > 0:
                response += f"  - Population: {dest['population']:,}\n"
            
            # Add activities if available
            if "activities" in dest and dest["activities"]:
                activities = dest["activities"][:3]  # Limit to 3 activities
                response += f"  - Top activities: {', '.join(activities)}\n"
            
            # Add budget estimate
            daily_budget = self.get_estimated_budget(dest)
            response += f"  - Estimated daily cost: ${daily_budget} per person\n"
            
            # Add budget level
            budget_level = dest.get("budget_level", "medium")
            response += f"  - Budget level: {budget_level.title()}\n"
            
            # Add budget assessment if user specified a budget
            if budget:
                total_trip_cost = daily_budget * 7  # Assume a 7-day trip
                if total_trip_cost <= budget * 0.7:
                    response += f"  - Budget assessment: Excellent value for your ${budget} budget\n"
                elif total_trip_cost <= budget:
                    response += f"  - Budget assessment: Good match for your ${budget} budget\n"
                else:
                    response += f"  - Budget assessment: May be tight for your ${budget} budget\n"
            
            # Add sample itinerary preview
            response += f"\n  Sample itinerary preview:\n"
            response += self._generate_itinerary_preview(dest['name'])
            response += "\n\n"
        
        # Add follow-up prompt
        follow_up = random.choice([
            "Would you like a detailed itinerary for any of these destinations?",
            "Shall I create a full itinerary for one of these options?",
            "Would you like more information about any of these destinations?"
        ])
        response += follow_up
        
        return response

    def _get_nearby_attractions(self, destination: Dict) -> List[str]:
        """Get nearby attractions for a destination."""
        nearby = []
        if "lat" in destination and "lng" in destination:
            nearby_places = self.location_service.get_nearby_places(
                destination["lat"], destination["lng"], radius=5, max_rows=3
            )
            nearby = [
                place.get("name") for place in nearby_places 
                if place.get("name") != destination["name"]
            ]
        return nearby

    def _generate_itinerary_preview(self, destination_name: str) -> str:
        """Generate a brief itinerary preview."""
        preview_templates = [
            f"A 3-day trip to {destination_name} could include exploring the city center, "
            "visiting top attractions, and enjoying local cuisine.",
            
            f"Your {destination_name} adventure might feature cultural experiences, "
            "delicious food, and scenic views.",
            
            f"In {destination_name}, you could spend your days sightseeing, relaxing, "
            "and immersing yourself in local culture."
        ]
        return random.choice(preview_templates)
    
    def find_flights(self, origin, destination, date=None):
        """Find flights between two locations"""
        if not date:
            date = (datetime.now() + timedelta(days=30)).strftime("%Y/%m/%d")
        
        # Search for airports
        origin_airports = self.flight_service.search_airports(origin)
        destination_airports = self.flight_service.search_airports(destination)
        
        if not origin_airports or not destination_airports:
            return f"Could not find airports for {origin} and/or {destination}."
        
        # Use the first airport for each location
        origin_code = origin_airports[0]["code"]
        destination_code = destination_airports[0]["code"]
        
        # Get flights
        flights = self.flight_service.get_flights(origin_code, destination_code, date)
        
        if not flights:
            return f"No flights found from {origin} ({origin_code}) to {destination} ({destination_code}) on {date}."
        
        response = f"Flights from {origin} ({origin_code}) to {destination} ({destination_code}):\n\n"
        
        for i, flight in enumerate(flights, 1):
            departure_time = flight["departure"]["time"]
            arrival_time = flight["arrival"]["time"]
            duration = flight["duration"]
            hours = duration // 60
            minutes = duration % 60
            
            response += f"Flight {i}: {flight['carrier']} {flight['flight_number']}\n"
            response += f"  Departure: {departure_time}\n"
            response += f"  Arrival: {arrival_time}\n"
            response += f"  Duration: {hours}h {minutes}m\n\n"
        
        return response
    
    def get_weather_info(self, location):
        """Get weather information for a location"""
        # Search for the location
        destinations = self.location_service.search_destinations(location, max_rows=1)
        
        if not destinations:
            return f"Could not find weather information for {location}."
        
        dest = destinations[0]
        
        # Get weather forecast
        forecast = self.weather_service.get_forecast(dest["lat"], dest["lng"])
        
        if not forecast:
            return f"Weather forecast not available for {dest['name']}, {dest['country']}."
        
        response = f"Weather forecast for {dest['name']}, {dest['country']}:\n\n"
        
        for day in forecast:
            date = datetime.strptime(day["date"], "%Y-%m-%d").strftime("%A, %b %d")
            response += f"{date}: {day['conditions']}, {day['temp_min']}°C to {day['temp_max']}°C\n"
            response += f"  Precipitation: {day['precipitation_probability']}%\n\n"
        
        return response
    
    def get_travel_recommendations(self, preferences):
        """Get travel recommendations based on user preferences"""
        logger.info(f"Getting travel recommendations for: {preferences}")
        
        # Extract key preferences using regex patterns
        patterns = {
            "destination_type": r"(?:beach|mountain|city|rural|island|nature|culture|historical)",
            "budget": r"(?:budget|cheap|affordable|expensive|luxury|\$?\d+(?:\s*dollars?|\s*USD)?)",
            "duration": r"(?:\d+\s+days?|\d+\s+weeks?)",
            "activities": r"(?:hiking|swimming|shopping|museums|food|dining|adventure|relaxation)"
        }
        
        extracted_prefs = {}
        for key, pattern in patterns.items():
            matches = re.findall(pattern, preferences.lower())
            if matches:
                extracted_prefs[key] = matches
        
        # Extract budget if present
        budget = self.extract_budget(preferences)
        
        # Build a query based on extracted preferences
        query_parts = []
        
        if "destination_type" in extracted_prefs:
            query_parts.extend(extracted_prefs["destination_type"])
        
        if "activities" in extracted_prefs:
            query_parts.extend(extracted_prefs["activities"])
        
        # If no preferences could be extracted, use the original text
        if not query_parts:
            query = preferences
        else:
            query = " ".join(query_parts)
        
        # Search for destinations
        destinations = self.search_destinations(query)
        
        if not destinations:
            return "I couldn't find any destinations matching your preferences. Could you provide more details?"
        
        # Filter by budget if specified
        if budget:
            filtered_destinations = []
            for dest in destinations:
                # Get estimated daily budget based on destination
                daily_budget = self.get_estimated_budget(dest)
                # Assume a 7-day trip
                total_budget = daily_budget * 7
                
                if total_budget <= budget:
                    filtered_destinations.append(dest)
            
            # If we have budget-filtered results, use them
            if filtered_destinations:
                destinations = filtered_destinations
        
        # Use budget template if budget exists
        if budget:
            response = f"With your ${budget} budget, consider these options:\n\n"
        else:
            response = "Based on your preferences, here are some recommended destinations:\n\n"
        
        for i, dest in enumerate(destinations, 1):
            response += f"{i}. {dest['name']}, {dest['country']}\n"
            
            # Add activities information
            if "activities" in dest and dest["activities"]:
                activities = dest["activities"][:3]  # Limit to 3 activities
                response += f"   Perfect for: {', '.join(activities)}\n"
            
            # Add budget information
            budget_level = dest.get("budget_level", "medium")
            if budget_level == "low":
                response += "   Affordability: Budget-friendly destination\n"
            elif budget_level == "medium":
                response += "   Affordability: Moderately priced destination\n"
            else:  # high
                response += "   Affordability: Premium destination\n"
            
            # Add estimated daily budget
            daily_budget = self.get_estimated_budget(dest)
            response += f"   Estimated daily cost: ${daily_budget} per person\n"
            
            # Add budget assessment if user specified a budget
            if budget:
                total_trip_cost = daily_budget * 7  # Assume a 7-day trip
                if total_trip_cost <= budget * 0.7:
                    response += f"   Budget assessment: Excellent value for your ${budget} budget\n"
                elif total_trip_cost <= budget:
                    response += f"   Budget assessment: Good match for your ${budget} budget\n"
                else:
                    response += f"   Budget assessment: May be tight for your ${budget} budget\n"
            
            response += "\n"
        
        response += "Would you like more information about any of these destinations?"
        return response

    def get_estimated_budget(self, destination):
        """Get estimated daily budget for a destination"""
        country = destination.get('country', '')
        
        # Budget estimates by country (USD per day)
        high_budget = {
            "Switzerland": 250, "Norway": 230, "Iceland": 220, "Japan": 200,
            "Singapore": 190, "United States": 180, "United Kingdom": 170,
            "Australia": 160, "Denmark": 190, "Sweden": 180, "Finland": 170,
            "Ireland": 160, "France": 150, "Netherlands": 150
        }
        
        medium_budget = {
            "Spain": 120, "Italy": 130, "Germany": 140, "Canada": 140,
            "New Zealand": 130, "South Korea": 120, "Portugal": 110,
            "Greece": 100, "Czech Republic": 90, "Poland": 80
        }
        
        low_budget = {
            "Thailand": 50, "Vietnam": 40, "Cambodia": 35, "Laos": 35,
            "Indonesia": 45, "India": 30, "Nepal": 25, "Bolivia": 35,
            "Colombia": 40, "Mexico": 45, "Philippines": 40, "Sri Lanka": 35,
            "Morocco": 45, "Egypt": 40
        }
        
        # Check if country is in our budget dictionaries
        if country in high_budget:
            return high_budget[country]
        elif country in medium_budget:
            return medium_budget[country]
        elif country in low_budget:
            return low_budget[country]
        
        # Default estimates based on budget level
        budget_level = destination.get('budget_level', 'medium')
        if budget_level == 'high':
            return 180
        elif budget_level == 'low':
            return 40
        else:  # medium
            return 100
    
    def extract_budget(self, text):
        matches = re.findall(r'\$?(\d+)(?:\s*(?:dollars|USD))?', text)
        return int(matches[0]) if matches else None

    def process_query(self, query):
        """Process a travel-related query and return a response"""
        # Extract query type using regex patterns
        patterns = {
            "destination_search": r"(?:where to go|recommend destinations|suggest places|where should I visit)",
            "itinerary_request": r"(?:itinerary for|travel plan for|things to do in|activities in|visit|go to)",
            "flight_search": r"(?:flights from|flights to|flights between)",
            "weather_info": r"(?:weather in|weather forecast for|climate in)",
            "travel_recommendations": r"(?:recommend|suggest|looking for|\$\d+|budget of|within budget)",
            "excursion_search": r"(?:excursions in|things to do in|activities in|attractions in|places to visit in)"
        }
        
        # Handle yes/no responses contextually
        if hasattr(self, 'conversation_history') and self.conversation_history:
            last_query = self.conversation_history[-1]['query']
            last_response = self.conversation_history[-1]['response']
            
            if query.lower() in ['yes', 'more', 'sure', 'please']:
                if 'recommended destinations' in last_response or 'options matching your search' in last_response:
                    # Show detailed info about first recommendation
                    return self._show_destination_details(last_response)
                elif 'itinerary' in last_response:
                    return self._expand_itinerary(last_response)
        
        # Extract budget if present
        budget = self.extract_budget(query)
        
        # Determine query type
        query_type = None
        for key, pattern in patterns.items():
            if re.search(pattern, query, re.IGNORECASE):
                query_type = key
                break
        
        # If no specific query type is detected, try to determine if it's a destination name
        if not query_type:
            # Check if query looks like a destination name
            destinations = self.location_service.search_destinations(query, max_rows=1)
            if destinations:
                # If we found a destination, treat as an itinerary request
                query_type = "itinerary_request"
            else:
                # Default to travel recommendations
                query_type = "travel_recommendations"
        
        # Process based on query type
        if query_type == "destination_search":
            return self.plan_trip(query)
        elif query_type == "itinerary_request":
            # Extract destination - improved pattern to catch "go to X" format
            destination_match = re.search(r"(?:itinerary for|travel plan for|things to do in|activities in|visit|go to)\s+(?:the\s+)?([\w\s,]+)", query, re.IGNORECASE)
            
            # If no match found but query type is itinerary_request, use the query itself as destination
            if not destination_match and query_type == "itinerary_request":
                destination = query.strip()
            else:
                destination = destination_match.group(1).strip() if destination_match else None
                
            if destination:
                # Extract days if specified
                days_match = re.search(r"(\d+)\s+days?", query, re.IGNORECASE)
                days = int(days_match.group(1)) if days_match else 3
                return self.generate_itinerary(destination, days=days)
            else:
                return "Please specify a destination for your itinerary."
        elif query_type == "excursion_search":
            # Extract location for excursions
            location_match = re.search(r"(?:excursions in|things to do in|activities in|attractions in|places to visit in)\s+(?:the\s+)?([\w\s,]+)", query, re.IGNORECASE)
            
            if location_match:
                location = location_match.group(1).strip()
                # Search for the location
                destinations = self.location_service.search_destinations(location, max_rows=1)
                
                if destinations:
                    dest = destinations[0]
                    # Get nearby places
                    nearby = self.location_service.get_nearby_places(
                        dest["lat"], dest["lng"], radius=20, max_rows=10
                    )
                    
                    response = f"Top attractions and things to do in {dest['name']}, {dest['country']}:\n\n"
                    
                    if nearby:
                        for i, place in enumerate(nearby, 1):
                            if place.get("name") != dest["name"]:
                                response += f"{i}. {place.get('name')}\n"
                                if place.get("type"):
                                    response += f"   Type: {place.get('type')}\n"
                                response += "\n"
                    else:
                        # Fallback to generic activities
                        activities = [
                            f"Explore the historic center of {dest['name']}",
                            f"Visit local museums and galleries",
                            f"Experience the local cuisine at restaurants and cafes",
                            f"Shop at local markets and boutiques",
                            f"Take a guided city tour",
                            f"Enjoy the nightlife and entertainment",
                            f"Relax in parks and green spaces",
                            f"Take day trips to nearby attractions"
                        ]
                        
                        for i, activity in enumerate(activities, 1):
                            response += f"{i}. {activity}\n\n"
                    
                    return response
                else:
                    return f"I couldn't find information about {location}. Could you try another destination?"
            else:
                return "Please specify a location to find excursions and attractions."
        elif query_type == "flight_search":
            # Extract origin and destination
            match = re.search(r"flights from\s+([\w\s]+)\s+to\s+([\w\s]+)", query, re.IGNORECASE)
            if match:
                origin = match.group(1).strip()
                destination = match.group(2).strip()
                # Extract date if specified
                date_match = re.search(r"on\s+(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})", query, re.IGNORECASE)
                date = date_match.group(1) if date_match else None
                return self.find_flights(origin, destination, date)
            else:
                return "Please specify origin and destination for flight search."
        elif query_type == "weather_info":
            # Extract location
            match = re.search(r"weather (?:in|forecast for|for)\s+([\w\s]+)", query, re.IGNORECASE)
            if match:
                location = match.group(1).strip()
                return self.get_weather_info(location)
            else:
                return "Please specify a location for weather information."
        elif query_type == "travel_recommendations":
            return self.get_travel_recommendations(query)
        else:
            return "I'm not sure what you're asking for. Could you rephrase your query?"




    



class EnhancedTripPlanner(TripPlanner):
    """Enhanced version of TripPlanner with improved AI capabilities and Supabase integration"""
    
    def __init__(self):
        # Call the parent class's __init__ method to inherit its initialization
        super().__init__()
        self.conversation_history = []
        self.max_history_length = 5
        self.dense_retriever = None
        self.dense_search_pipeline = None
        self.combined_search_pipeline = None

        # Add RESPONSE_TEMPLATES attribute to match what's used in plan_trip method
        self.RESPONSE_TEMPLATES = {
            'destinations': [
                "Here are some great options matching your search:",
                "Based on your preferences, I recommend:",
                "You might enjoy these destinations:",
                "I found these perfect locations for you:",
                "Top picks for your travel plans:"
            ],
            'budget': [
                "With your ${budget} budget, consider these options:",
                "Here are destinations that fit your ${budget} budget:",
                "Great choices within your ${budget} range:"
            ]
        }
        
        # Initialize additional components for improved AI
        # We'll use a more sophisticated document retriever if possible
        try:
            from haystack.nodes import DensePassageRetriever
            self.dense_retriever = DensePassageRetriever(
                document_store=self.document_store,
                query_embedding_model="facebook/dpr-question_encoder-single-nq-base",
                passage_embedding_model="facebook/dpr-ctx_encoder-single-nq-base",
                use_gpu=False
            )
            logger.info("Dense retriever initialized")

        
            
            # Update the search pipeline to use both retrievers for better results
            self.dense_search_pipeline = Pipeline()
            self.dense_search_pipeline.add_node(component=self.dense_retriever, name="DenseRetriever", inputs=["Query"])
            
            # Add reader to dense pipeline if available
            if self.reader:
                self.dense_search_pipeline.add_node(component=self.reader, name="Reader", inputs=["DenseRetriever"])
                
            # Update document embeddings
            try:
                self.document_store.update_embeddings(self.dense_retriever)
            except Exception as e:
                logger.warning(f"Could not update embeddings: {e}")
                
            # Create a combined search pipeline if possible
            try:
                from haystack.nodes import JoinDocuments
                # Create combined pipeline with both retrievers
                self.combined_search_pipeline = Pipeline()
                self.combined_search_pipeline.add_node(component=self.retriever, name="BM25Retriever", inputs=["Query"])
                self.combined_search_pipeline.add_node(component=self.dense_retriever, name="DenseRetriever", inputs=["Query"])
                self.combined_search_pipeline.add_node(component=JoinDocuments(join_mode="reciprocal_rank_fusion"), 
                                                name="JoinResults", 
                                                inputs=["BM25Retriever", "DenseRetriever"])
                
                if self.reader:
                    self.combined_search_pipeline.add_node(component=self.reader, name="Reader", inputs=["JoinResults"])
                    
                logger.info("Combined search pipeline successfully initialized.")
            except Exception as e:
                logger.warning(f"Combined search pipeline could not be initialized: {e}")
                self.combined_search_pipeline = None
                
        except Exception as e:
            logger.warning(f"Dense retriever could not be initialized due to: {e}")
            logger.info("Using default BM25 retriever only.")
    
    def update_destination_data(self):
        """Enhanced method to update destination data with more detailed information"""
        # First call the parent method
        super().update_destination_data()
        
        # Add more comprehensive travel knowledge
        additional_docs = []


        
        
        # Add travel tips and guides
        
        travel_tips = [
            {
                "content": "When traveling internationally, always check visa requirements well in advance. "
                          "Many countries require visas to be obtained before arrival, and processing times can vary.",
                "meta": {
                    "type": "travel_tip",
                    "category": "planning",
                    "tags": ["visa", "international", "preparation"]
                }
            },
            {
                "content": "Pack light and smart. Consider the weather at your destination and activities planned. "
                          "Rolling clothes saves space and reduces wrinkles.",
                "meta": {
                    "type": "travel_tip",
                    "category": "packing",
                    "tags": ["luggage", "preparation", "clothing"]
                }
            },
            {
                "content": "Travel insurance is essential for international trips. It can cover medical emergencies, "
                          "trip cancellations, lost luggage, and other unexpected events.",
                "meta": {
                    "type": "travel_tip",
                    "category": "planning",
                    "tags": ["insurance", "safety", "preparation"]
                }
            }
        ]
        
        # Convert tips to documents and add to collection
        for tip in travel_tips:
            additional_docs.append(Document(content=tip["content"], meta=tip["meta"]))
        
        # Add more destination-specific information
        destinations_info = [
            {
                "content": "Paris, France: Known as the 'City of Light', Paris is famous for the Eiffel Tower, "
                          "Louvre Museum, Notre-Dame Cathedral, and its exquisite cuisine. The city is divided into "
                          "20 arrondissements (districts), with the Seine River running through the center.",
                "meta": {
                    "name": "Paris",
                    "country": "France",
                    "type": "destination_info",
                    "attractions": ["Eiffel Tower", "Louvre Museum", "Notre-Dame Cathedral"],
                    "tags": ["city", "culture", "romance", "history", "art"]
                }
            },
            {
                "content": "Tokyo, Japan: A bustling metropolis that blends ultramodern and traditional aspects. "
                          "Tokyo features skyscrapers, historic temples, and a vibrant food scene. Key attractions include "
                          "Tokyo Skytree, Senso-ji Temple, and the Shibuya Crossing.",
                "meta": {
                    "name": "Tokyo",
                    "country": "Japan",
                    "type": "destination_info",
                    "attractions": ["Tokyo Skytree", "Senso-ji Temple", "Shibuya Crossing"],
                    "tags": ["city", "technology", "culture", "food", "shopping"]
                }
            }
        ]
        
        # Convert destination info to documents and add to collection
        for info in destinations_info:
            additional_docs.append(Document(content=info["content"], meta=info["meta"]))
        
        # Write additional documents to the document store
        if additional_docs:
            try:
                self.document_store.write_documents(additional_docs)
                logger.info(f"Added {len(additional_docs)} additional travel knowledge documents")
                
                # Update embeddings if dense retriever is available
                if self.dense_retriever:
                    self.document_store.update_embeddings(self.dense_retriever)
            except Exception as e:
                logger.error(f"Error adding additional documents: {e}")
    
    def search_destinations(self, query, top_k=3):
        """Enhanced destination search using improved retrieval methods"""
        logger.info(f"Searching for destinations with query: {query}")
        
        # First try direct search with the location service
        direct_results = self.location_service.search_destinations(query, max_rows=top_k*2)
        
        # Process direct results
        destinations = []
        seen = set()
        
        for dest in direct_results:
            key = (dest["name"], dest["country"])
            if key not in seen:
                seen.add(key)
                
                # Enhance with nearby attractions
                nearby_places = self.location_service.get_nearby_places(
                    dest["lat"], dest["lng"], radius=10, max_rows=5
                )
                
                # Create activities based on nearby places
                activities = []
                for place in nearby_places:
                    if place.get("name") != dest["name"]:
                        activities.append(f"Visit {place.get('name')}")
                
                # Add some generic activities if we don't have enough
                if len(activities) < 3:
                    generic_activities = [
                        f"Explore the city center of {dest['name']}",
                        f"Try local cuisine in {dest['name']}",
                        f"Shop at local markets",
                        f"Visit museums and galleries",
                        f"Take a guided city tour"
                    ]
                    activities.extend(generic_activities)
                
                # Add budget level based on country
                budget_level = self._determine_budget_level(dest["country"])
                
                # Create enhanced destination object
                enhanced_dest = {
                    "name": dest["name"],
                    "country": dest["country"],
                    "lat": dest["lat"],
                    "lng": dest["lng"],
                    "population": dest.get("population", 0),
                    "activities": activities[:5],  # Limit to 5 activities
                    "budget_level": budget_level
                }
                
                destinations.append(enhanced_dest)
        
        # If we don't have enough results from direct search, try the document store
        if len(destinations) < top_k and self.combined_search_pipeline:
            try:
                results = self.combined_search_pipeline.run(
                    query=query, 
                    params={"BM25Retriever": {"top_k": top_k}, "DenseRetriever": {"top_k": top_k}}
                )
                
                for doc in results["documents"]:
                    if "name" in doc.meta and "country" in doc.meta:
                        key = (doc.meta["name"], doc.meta.get("country", "Unknown"))
                        if key not in seen:
                            seen.add(key)
                            
                            # Create enhanced destination from document
                            dest = {
                                "name": doc.meta["name"],
                                "country": doc.meta.get("country", "Unknown"),
                                "lat": doc.meta.get("lat", 0),
                                "lng": doc.meta.get("lng", 0),
                                "population": doc.meta.get("population", 0),
                                "activities": doc.meta.get("activities", []),
                                "budget_level": doc.meta.get("budget_level", self._determine_budget_level(doc.meta.get("country", "Unknown")))
                            }
                            destinations.append(dest)
            except Exception as e:
                logger.error(f"Error using combined search pipeline: {e}")
        
        # If we still don't have enough results, try a broader search
        if len(destinations) < top_k:
            try:
                # Try a more general search with different parameters
                broader_results = self.location_service.search_destinations(
                    query, 
                    max_rows=top_k*2, 
                    feature_class="P"
                )
                
                for dest in broader_results:
                    key = (dest["name"], dest["country"])
                    if key not in seen:
                        seen.add(key)
                        
                        # Add budget level and activities
                        budget_level = self._determine_budget_level(dest["country"])
                        activities = [
                            f"Explore {dest['name']}",
                            f"Experience local culture in {dest['name']}",
                            f"Try authentic cuisine"
                        ]
                        
                        enhanced_dest = {
                            "name": dest["name"],
                            "country": dest["country"],
                            "lat": dest["lat"],
                            "lng": dest["lng"],
                            "population": dest.get("population", 0),
                            "activities": activities,
                            "budget_level": budget_level
                        }
                        
                        destinations.append(enhanced_dest)
            except Exception as e:
                logger.error(f"Error in broader search: {e}")
        
        # If we still have no results, add some fallback destinations
        if not destinations:
            logger.warning(f"No results found for '{query}', using fallback destinations")
            
            # Try to match query with common city names before using generic fallbacks
            query_lower = query.lower()
            common_cities = {
                "paris": {
                    "name": "Paris",
                    "country": "France",
                    "lat": 48.8566,
                    "lng": 2.3522,
                    "population": 2140526,
                    "activities": ["Visit Eiffel Tower", "Explore Louvre Museum", "Stroll along Seine River"],
                    "budget_level": "high"
                },
                "rome": {
                    "name": "Rome",
                    "country": "Italy",
                    "lat": 41.9028,
                    "lng": 12.4964,
                    "population": 2873000,
                    "activities": ["Visit Colosseum", "Explore Vatican Museums", "Throw a coin in Trevi Fountain"],
                    "budget_level": "medium"
                },
                "barcelona": {
                    "name": "Barcelona",
                    "country": "Spain",
                    "lat": 41.3851,
                    "lng": 2.1734,
                    "population": 1620343,
                    "activities": ["Visit Sagrada Familia", "Explore Park Güell", "Stroll along La Rambla"],
                    "budget_level": "medium"
                },
                "tokyo": {
                    "name": "Tokyo",
                    "country": "Japan",
                    "lat": 35.6762,
                    "lng": 139.6503,
                    "population": 13960000,
                    "activities": ["Visit Tokyo Skytree", "Explore Senso-ji Temple", "Experience Shibuya Crossing"],
                    "budget_level": "high"
                },
                "new york": {
                    "name": "New York",
                    "country": "United States",
                    "lat": 40.7128,
                    "lng": -74.0060,
                    "population": 8804190,
                    "activities": ["Visit Times Square", "Explore Central Park", "See Statue of Liberty"],
                    "budget_level": "high"
                }
            }
            
            # Check for exact or partial matches in common cities
            matched_cities = []
            for city_key, city_data in common_cities.items():
                if query_lower == city_key or query_lower in city_key or city_key in query_lower:
                    matched_cities.append(city_data)
            
            if matched_cities:
                destinations = matched_cities
            else:
                # If no specific match, return a diverse set of fallbacks
                destinations = list(common_cities.values())
        
        logger.info(f"Found {len(destinations)} destinations for query: {query}")
        return destinations[:top_k]

    def _determine_budget_level(self, country):
        """Determine budget level based on country"""
        high_budget_countries = ["Switzerland", "Norway", "Iceland", "Japan", "Singapore", 
                                "United States", "United Kingdom", "Australia", "Denmark", 
                                "Sweden", "Finland", "Ireland", "France", "Netherlands"]
        
        low_budget_countries = ["Thailand", "Vietnam", "Cambodia", "Laos", "Indonesia", 
                            "India", "Nepal", "Bolivia", "Colombia", "Mexico", 
                            "Philippines", "Sri Lanka", "Morocco", "Egypt"]
        
        if country in high_budget_countries:
            return "high"
        elif country in low_budget_countries:
            return "low"
        else:
            return "medium"
    
    def add_to_conversation_history(self, query, response):
        """Add a query-response pair to the conversation history"""
        self.conversation_history.append({"query": query, "response": response})
        # Keep history to the last N interactions
        if len(self.conversation_history) > self.max_history_length:
            self.conversation_history = self.conversation_history[-self.max_history_length:]
    
    def get_conversation_context(self):
        """Extract context from conversation history"""
        if not self.conversation_history:
            return ""
            
        context = "Based on our conversation so far, you've shown interest in: "
        
        # Extract key terms from past queries
        all_queries = " ".join([item["query"] for item in self.conversation_history])
        
        # Simple keyword extraction
        keywords = []
        potential_keywords = ["beach", "mountain", "city", "culture", "food", "adventure", 
                             "budget", "luxury", "family", "solo", "couple", "history",
                             "nature", "relaxation", "shopping"]
        
        for keyword in potential_keywords:
            if keyword.lower() in all_queries.lower():
                keywords.append(keyword)
        
        # Extract mentioned destinations
        import re
        destinations = re.findall(r"(?:visit|go to|travel to|trip to|in)\s+(?:the\s+)?([\w\s]+)", all_queries, re.IGNORECASE)
        
        if keywords:
            context += f"{', '.join(keywords)}. "
            
        if destinations:
            # Clean up destination names
            cleaned_destinations = [d.strip() for d in destinations if len(d.strip()) > 2]
            if cleaned_destinations:
                context += f"You've mentioned these destinations: {', '.join(cleaned_destinations)}. "
        
        return context
    
    def process_query(self, query):
        """Enhanced query processing with context awareness"""
        # Check if this is a follow-up question
        is_followup = len(self.conversation_history) > 0 and not any(
            re.search(pattern, query, re.IGNORECASE) 
            for pattern in [
                "where to go", "recommend destinations", "suggest places", 
                "itinerary for", "travel plan for", "flights from", "weather in"
            ]
        )
        
        # If it's a follow-up, add context from conversation history
        if is_followup:
            context = self.get_conversation_context()
            contextual_query = f"{context} {query}"
            logger.info(f"Enhanced query with context: {contextual_query}")
            response = super().process_query(contextual_query)
        else:
            response = super().process_query(query)
        
        # Store in conversation history
        self.add_to_conversation_history(query, response)
        
        return response
    
if __name__ == "__main__":
    print("Welcome to the Trip Planner!")
    print("Please enter your travel-related query (or 'exit' to quit):")
    
    # Use EnhancedTripPlanner instead of TripPlanner
    planner = EnhancedTripPlanner()
    
    while True:
        user_query = input("> ")
        
        if user_query.lower() in ["exit", "quit", "bye"]:
            print("Thank you for using the Trip Planner. Goodbye!")
            break
        
        try:
            response = planner.process_query(user_query)
            print("\n" + response + "\n")
        except Exception as e:
            print(f"\nError processing query: {str(e)}\n")
            print("Please try rephrasing your query or try another destination.")
    


class TravelApp:
    """Main application class that coordinates between TripPlanner and Supabase"""
    
    def __init__(self, supabase_url, supabase_key):
        # Initialize the enhanced trip planner
        self.trip_planner = EnhancedTripPlanner()
        
        # Initialize Supabase client
        self.supabase = create_client(supabase_url, supabase_key)
        
    def handle_user_query(self, user_id, query):
        """Process a user query and store the interaction in Supabase"""
        # Process the query with the AI
        response = self.trip_planner.process_query(query)
        
        # Store the query and response in Supabase
        try:
            self.supabase.table('query_history').insert({
                'user_id': user_id,
                'query': query,
                'response': response,
                'timestamp': datetime.now().isoformat()
            }).execute()
            logger.info(f"Stored query history for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to store query history: {e}")
        
        return response
        
    def save_trip_plan(self, user_id, destination, itinerary):
        """Save a generated trip plan to Supabase"""
        try:
            result = self.supabase.table('trip_plans').insert({
                'user_id': user_id,
                'destination': destination,
                'itinerary': itinerary,
                'created_at': datetime.now().isoformat()
            }).execute()
            logger.info(f"Saved trip plan for {destination} for user {user_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to save trip plan: {e}")
            return None
            
    def get_user_trips(self, user_id):
        """Get all trip plans for a user"""
        try:
            result = self.supabase.table('trip_plans').select('*').eq('user_id', user_id).execute()
            return result.data
        except Exception as e:
            logger.error(f"Failed to get user trips: {e}")
            return []
            
    def save_user_preferences(self, user_id, preferences):
        """Save user travel preferences to Supabase"""
        try:
            # Check if preferences already exist
            existing = self.supabase.table('user_preferences').select('*').eq('user_id', user_id).execute()
            
            if existing.data:
                # Update existing preferences
                result = self.supabase.table('user_preferences').update(preferences).eq('user_id', user_id).execute()
            else:
                # Insert new preferences
                preferences['user_id'] = user_id
                result = self.supabase.table('user_preferences').insert(preferences).execute()
                
            logger.info(f"Saved preferences for user {user_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to save user preferences: {e}")
            return None
            
    def get_user_preferences(self, user_id):
        """Get user travel preferences from Supabase"""
        try:
            result = self.supabase.table('user_preferences').select('*').eq('user_id', user_id).execute()
            if result.data:
                return result.data[0]
            return {}
        except Exception as e:
            logger.error(f"Failed to get user preferences: {e}")
            return {}