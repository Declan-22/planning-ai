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


from haystack.document_stores import InMemoryDocumentStore
from haystack.nodes import BM25Retriever
from haystack.schema import Document
from haystack import Pipeline
import os
import json
import time
import requests
from datetime import datetime, timedelta
import logging
import re

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
            
            return destinations[:max_rows]
            
        except Exception as e:
            logger.error(f"GeoNames API error: {str(e)}")
            return self._fallback_search(query, max_rows)

    def _fallback_search(self, query, max_rows):
        """Fallback search when Geonames API fails."""
        logger.info("Using local fallback data")
        
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
            # Add more destinations...
        }
        
        query_lower = query.lower()
        results = []
        
        # Exact match
        if query_lower in fallback_data:
            return [fallback_data[query_lower]]
            
        # Partial matches
        for key, data in fallback_data.items():
            if query_lower in key or any(word in key for word in query_lower.split()):
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

class TripPlanner:
    """Main class for planning trips and generating itineraries"""
    
    def __init__(self):
        self.location_service = LocationService(username="curiousclump")  # Add your username here
        self.route_service = RouteService()
        self.flight_service = FlightService()
        self.weather_service = WeatherService()
        self.document_store = document_store
        
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
    
    def update_destination_data(self):
        """Update destination data in the document store with popular destinations"""
        popular_locations = [

        ]
        
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
            # Add fallback documents
            for location in popular_locations:
                content = f"{location}: A popular tourist destination. Activities include sightseeing, local cuisine, and cultural experiences."
                metadata = {
                    "name": location,
                    "country": "Unknown",
                    "activities": ["Sightseeing", "Try local cuisine", "Cultural experiences"],
                    "tags": ["city", "tourism", "travel"]
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
            
            # Afternoon
            itinerary += "\nAfternoon:\n"
            for i in range(start_idx + 1, min(start_idx + 3, end_idx)):
                itinerary += f"- {activities[i]}\n"
                
            # Adjust afternoon activities based on weather
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
    
    def plan_trip(self, query):
        """Create a trip plan based on user query"""
        logger.info(f"Searching for destinations based on query: {query}")
        destinations = self.search_destinations(query)
        
        if not destinations:
            return "I couldn't find any suitable destinations for your preferences. Could you provide more details about what you're looking for?"
        
        response = "Based on your preferences, here are some recommended destinations:\n\n"
        
        for i, dest in enumerate(destinations, 1):
            response += f"Option {i}: {dest['name']}, {dest['country']}\n"
            
            # Get nearby attractions
            nearby = []
            if "lat" in dest and "lng" in dest:
                nearby_places = self.location_service.get_nearby_places(
                    dest["lat"], dest["lng"], radius=5, max_rows=3
                )
                nearby = [place.get("name") for place in nearby_places if place.get("name") != dest["name"]]
            
            # Add nearby attractions to the description
            nearby_str = ""
            if nearby:
                nearby_str = f" Nearby attractions include {', '.join(nearby)}."
            
            # Add population info if available
            if dest.get("population", 0) > 0:
                population_str = f" Population: {dest['population']:,}"
                response += f"  - {population_str}{nearby_str}\n"
            else:
                response += f"  - {nearby_str}\n"
            
            # Add activities if available
            if "activities" in dest and dest["activities"]:
                activities = dest["activities"][:3]  # Limit to 3 activities
                response += f"  - Activities: {', '.join(activities)}\n"
            
            # Add sample itinerary - Fix the preview portion
            response += f"\nSample itinerary preview for {dest['name']}:\n"
            # Generate a small preview instead of trying to split the full itinerary
            preview = f"A {3}-day trip could include exploring the city center, " + \
                     f"visiting nearby attractions, and experiencing local cuisine."
            response += preview + "\n\n"
        
        response += "Would you like a detailed itinerary for any of these destinations? Or would you like to refine your search with more specific preferences?"
        return response
    
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
        # Extract key preferences using regex patterns
        patterns = {
            "destination_type": r"(?:beach|mountain|city|rural|island|nature|culture|historical)",
            "budget": r"(?:budget|cheap|affordable|expensive|luxury)",
            "duration": r"(?:\d+\s+days?|\d+\s+weeks?)",
            "activities": r"(?:hiking|swimming|shopping|museums|food|dining|adventure|relaxation)"
        }
        
        extracted_prefs = {}
        for key, pattern in patterns.items():
            matches = re.findall(pattern, preferences.lower())
            if matches:
                extracted_prefs[key] = matches
        
        # Build a query based on extracted preferences
        query_parts = []
        
        if "destination_type" in extracted_prefs:
            query_parts.extend(extracted_prefs["destination_type"])
        
        if "activities" in extracted_prefs:
            query_parts.extend(extracted_prefs["activities"])
        
        if "budget" in extracted_prefs:
            budget_terms = extracted_prefs["budget"]
            if any(term in ["budget", "cheap", "affordable"] for term in budget_terms):
                query_parts.append("affordable")
            elif any(term in ["expensive", "luxury"] for term in budget_terms):
                query_parts.append("luxury")
        
        # If no preferences could be extracted, use the original text
        if not query_parts:
            query = preferences
        else:
            query = " ".join(query_parts)
        
        # Search for destinations
        destinations = self.search_destinations(query)
        
        if not destinations:
            return "I couldn't find any destinations matching your preferences. Could you provide more details?"
        
        response = "Based on your preferences, here are some recommended destinations:\n\n"
        
        for i, dest in enumerate(destinations, 1):
            response += f"{i}. {dest['name']}, {dest['country']}\n"
            
            # Add a brief description
            if "activities" in dest and dest["activities"]:
                activities = dest["activities"][:3]
                response += f"   Perfect for: {', '.join(activities)}\n"
            
            # Add budget information if available
            if "budget" in extracted_prefs:
                budget_terms = extracted_prefs["budget"]
                if any(term in ["budget", "cheap", "affordable"] for term in budget_terms):
                    response += "   Affordability: Good for budget travelers\n"
                elif any(term in ["expensive", "luxury"] for term in budget_terms):
                    response += "   Affordability: Luxury destination\n"
            
            response += "\n"
        
        response += "Would you like more information about any of these destinations?"
        return response


    def process_query(self, query):
        """Process a travel-related query and return a response"""
        # Extract query type using regex patterns
        patterns = {
            "destination_search": r"(?:where to go|recommend destinations|suggest places|where should I visit)",
            "itinerary_request": r"(?:itinerary for|travel plan for|things to do in|activities in|visit|go to)",
            "flight_search": r"(?:flights from|flights to|flights between)",
            "weather_info": r"(?:weather in|weather forecast for|climate in)",
            "travel_recommendations": r"(?:recommend|suggest|looking for)"
        }
        
        query_type = None
        for key, pattern in patterns.items():
            if re.search(pattern, query, re.IGNORECASE):
                query_type = key
                break
        
        # If no specific query type is detected, treat as general travel recommendations
        if not query_type:
            query_type = "travel_recommendations"
        
        # Process based on query type
        if query_type == "destination_search":
            return self.plan_trip(query)
        elif query_type == "itinerary_request":
            # Extract destination - improved pattern to catch "go to X" format
            destination_match = re.search(r"(?:itinerary for|travel plan for|things to do in|activities in|visit|go to)\s+(?:the\s+)?([\w\s]+)", query, re.IGNORECASE)
            if destination_match:
                destination = destination_match.group(1).strip()
                # Extract days if specified
                days_match = re.search(r"(\d+)\s+days?", query, re.IGNORECASE)
                days = int(days_match.group(1)) if days_match else 3
                return self.generate_itinerary(destination, days=days)
            else:
                return "Please specify a destination for your itinerary."
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



def process_query(query):
    """Process a travel-related query and return a response"""
    planner = TripPlanner()
    return planner.process_query(query)


if __name__ == "__main__":
    # Example usage
    print("Welcome to the Trip Planner!")
    print("Please enter your travel-related query (or 'exit' to quit):")
    
    # Create a single TripPlanner instance to avoid reinitializing for each query
    planner = TripPlanner()
    
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