from haystack.document_stores import InMemoryDocumentStore
from haystack.nodes import BM25Retriever
from haystack.schema import Document
from haystack import Pipeline
import os
import json
import time

try:
    # Try to import optional components if available
    from haystack.nodes import FARMReader
    has_reader = True
except ImportError:
    has_reader = False

# Initialize document store
document_store = InMemoryDocumentStore(use_bm25=True)

# More comprehensive destination dataset
destinations = [
    {
        "name": "Paris",
        "country": "France",
        "description": "Paris is known as the City of Light and offers iconic landmarks like the Eiffel Tower, Louvre Museum, and Notre-Dame Cathedral. The city is divided into 20 arrondissements, each with its own character. Visitors can enjoy world-class cuisine, fashion, art, and a romantic atmosphere along the Seine River.",
        "activities": ["Visit the Eiffel Tower", "Explore the Louvre Museum", "Stroll along Champs-Élysées", "Take a Seine River cruise", "Visit Notre-Dame Cathedral", "Explore Montmartre and Sacré-Cœur"],
        "best_time": "April to June and October to November",
        "budget_range": "High",
        "tags": ["romantic", "art", "food", "city", "culture", "history", "architecture", "museums"]
    },
    {
        "name": "Tokyo",
        "country": "Japan",
        "description": "Tokyo is a dynamic metropolis that blends ultramodern and traditional aspects of Japanese culture. The city offers cutting-edge technology, incredible public transportation, historic temples, and world-renowned cuisine. From the bustling streets of Shibuya to the serene gardens of the Imperial Palace, Tokyo presents countless unique experiences.",
        "activities": ["Visit Senso-ji Temple", "Experience Shibuya Crossing", "Explore the Tokyo Imperial Palace", "Shop in Ginza", "Visit teamLab Borderless Digital Art Museum", "Enjoy sushi at Tsukiji Outer Market"],
        "best_time": "March to April and September to November",
        "budget_range": "High",
        "tags": ["modern", "food", "culture", "city", "shopping", "technology", "temples", "anime"]
    },
    {
        "name": "Kyoto",
        "country": "Japan",
        "description": "Kyoto served as Japan's capital for over 1,000 years and remains the cultural heart of Japan. With over 1,600 Buddhist temples, 400 Shinto shrines, and 17 UNESCO World Heritage sites, it offers incredible historical experiences. The city preserves traditional wooden architecture, Japanese gardens, and geisha culture in the Gion district.",
        "activities": ["Visit Fushimi Inari Shrine", "Explore Arashiyama Bamboo Grove", "Tour Kinkaku-ji (Golden Pavilion)", "Experience a traditional tea ceremony", "Stroll through Gion district", "Visit Kiyomizu-dera Temple"],
        "best_time": "March to May and October to November",
        "budget_range": "Medium to High",
        "tags": ["traditional", "culture", "temples", "history", "gardens", "peaceful", "shrines"]
    },
    {
        "name": "Bali",
        "country": "Indonesia",
        "description": "Bali is known as the Island of the Gods, offering stunning landscapes from volcanic mountains to lush rice terraces and pristine beaches. The island blends spirituality, relaxation, and adventure with its unique Hindu culture, world-class surfing, yoga retreats, and vibrant arts scene. Each region of Bali has its own character, from bustling Kuta to serene Ubud.",
        "activities": ["Relax on Kuta Beach", "Explore the Sacred Monkey Forest Sanctuary", "Visit Tanah Lot Temple", "Tour the Tegallalang Rice Terraces", "Enjoy water sports in Nusa Dua", "Experience a traditional Balinese spa"],
        "best_time": "April to October (dry season)",
        "budget_range": "Low to Medium",
        "tags": ["beach", "relaxation", "nature", "island", "spiritual", "tropical", "surfing", "yoga"]
    },
    {
        "name": "Santorini",
        "country": "Greece",
        "description": "Santorini is a volcanic island in the Cyclades group of the Greek islands, famous for its dramatic views, stunning sunsets, white-washed buildings with blue domes, and crystal-clear waters. The island's unique landscape was formed by a massive volcanic eruption, creating its iconic caldera and cliffs. The main towns of Fira and Oia offer charming narrow streets, boutique hotels, and excellent dining options.",
        "activities": ["Watch the sunset in Oia", "Visit ancient Akrotiri ruins", "Swim at Red Beach", "Take a caldera cruise", "Visit wineries", "Explore Fira's narrow streets"],
        "best_time": "April to May and September to October",
        "budget_range": "High",
        "tags": ["romantic", "island", "views", "beach", "relaxation", "luxury", "sunsets", "wine"]
    },
    {
        "name": "New York City",
        "country": "USA",
        "description": "New York City is a global center for media, culture, fashion, finance, and commerce. The city's iconic skyline includes the Empire State Building, Statue of Liberty, and One World Trade Center. With diverse neighborhoods, world-class museums, Broadway shows, and cuisine from every corner of the world, NYC offers endless exploration opportunities. Central Park provides a green oasis amid the urban landscape.",
        "activities": ["Visit Times Square", "Explore Central Park", "Tour the Metropolitan Museum of Art", "See a Broadway show", "Visit the Statue of Liberty", "Walk across Brooklyn Bridge"],
        "best_time": "April to June and September to November",
        "budget_range": "High",
        "tags": ["urban", "art", "shopping", "city", "food", "entertainment", "museums", "nightlife", "theater"]
    },
    {
        "name": "Costa Rica",
        "country": "Costa Rica",
        "description": "Costa Rica is a paradise for nature lovers and adventure seekers, offering incredible biodiversity within its rainforests, cloud forests, beaches, and volcanoes. The country is known for its conservation efforts, with approximately 25% of its land protected as national parks or reserves. Visitors can experience zip-lining, wildlife viewing, surfing, and the laid-back 'pura vida' lifestyle.",
        "activities": ["Zip-line through Monteverde Cloud Forest", "Visit Arenal Volcano", "Surf in Tamarindo", "Wildlife spotting in Manuel Antonio National Park", "Relax at hot springs", "Take a coffee plantation tour"],
        "best_time": "December to April (dry season)",
        "budget_range": "Medium",
        "tags": ["nature", "adventure", "wildlife", "beach", "eco-friendly", "rainforest", "volcanoes", "surfing"]
    },
    {
        "name": "Rome",
        "country": "Italy",
        "description": "Rome, the Eternal City, offers nearly 3,000 years of globally influential art, architecture, and culture. Ancient ruins like the Colosseum and Roman Forum stand alongside Renaissance masterpieces and modern Italian life. The Vatican City, an independent state within Rome, houses St. Peter's Basilica and the Vatican Museums. Rome's piazzas, trattorias, and gelaterias provide authentic Italian experiences at every turn.",
        "activities": ["Visit the Colosseum and Roman Forum", "Explore Vatican City and St. Peter's Basilica", "Throw a coin in Trevi Fountain", "Visit the Pantheon", "Enjoy authentic Italian cuisine", "Explore Trastevere neighborhood"],
        "best_time": "April to May and September to October",
        "budget_range": "Medium to High",
        "tags": ["history", "food", "architecture", "city", "art", "culture", "ancient", "museums", "religious"]
    }
]

# Convert sample data to Haystack Document objects
docs = []
for dest in destinations:
    content = f"{dest['name']}, {dest['country']}: {dest['description']} Activities include: {', '.join(dest['activities'])}. Best time to visit: {dest['best_time']}. Budget: {dest['budget_range']}."
    metadata = {
        "name": dest["name"],
        "country": dest["country"],
        "best_time": dest["best_time"],
        "budget_range": dest["budget_range"],
        "tags": dest["tags"],
        "activities": dest["activities"]
    }
    docs.append(Document(content=content, meta=metadata))

# Write documents to the document store
document_store.write_documents(docs)

# Initialize retriever
retriever = BM25Retriever(document_store=document_store)

# Create a search pipeline
search_pipeline = Pipeline()
search_pipeline.add_node(component=retriever, name="Retriever", inputs=["Query"])

# Add a reader if available (for more advanced question answering)
if has_reader:
    try:
        reader = FARMReader(model_name_or_path="deepset/roberta-base-squad2", use_gpu=False)
        search_pipeline.add_node(component=reader, name="Reader", inputs=["Retriever"])
    except Exception as e:
        print(f"Reader could not be initialized due to: {e}")
        print("Running with retriever only mode.")

def generate_itinerary(destination, days=3):
    """Generate a day-by-day itinerary for a destination"""
    # Find the destination in our data
    dest = None
    for d in destinations:
        if d["name"].lower() == destination.lower():
            dest = d
            break
    
    if not dest:
        return f"Could not generate itinerary for {destination}. Destination not found in database."
    
    # Simple itinerary generation based on activities
    activities = dest["activities"]
    itinerary = f"\n{days}-Day Itinerary for {dest['name']}, {dest['country']}:\n"
    
    # Distribute activities across days
    activities_per_day = max(1, len(activities) // days)
    
    for day in range(1, days + 1):
        itinerary += f"\nDay {day}:\n"
        start_idx = (day - 1) * activities_per_day
        end_idx = min(start_idx + activities_per_day, len(activities))
        
        if day == days:  # Last day gets any remaining activities
            end_idx = len(activities)
        
        # Morning
        itinerary += "Morning:\n"
        if start_idx < end_idx:
            itinerary += f"- {activities[start_idx]}\n"
            itinerary += "- Breakfast at a local café\n"
        
        # Afternoon
        itinerary += "\nAfternoon:\n"
        if start_idx + 1 < end_idx:
            itinerary += f"- {activities[start_idx + 1]}\n"
        if start_idx + 2 < end_idx:
            itinerary += f"- {activities[start_idx + 2]}\n"
        itinerary += "- Lunch at a recommended restaurant\n"
        
        # Evening
        itinerary += "\nEvening:\n"
        itinerary += "- Dinner at a local restaurant\n"
        if day == 1:
            itinerary += "- Evening stroll to explore the area\n"
        elif day == days:
            itinerary += "- Farewell dinner with local specialties\n"
        else:
            itinerary += "- Relax and enjoy local entertainment\n"
    
    # Add travel tips
    itinerary += f"\nTravel Tips for {dest['name']}:\n"
    itinerary += f"- Best time to visit: {dest['best_time']}\n"
    itinerary += f"- Budget range: {dest['budget_range']}\n"
    itinerary += "- Remember to research local customs and etiquette\n"
    itinerary += "- Check for any required travel documents or vaccinations\n"
    
    return itinerary

def find_destinations(query, top_k=3):
    """Search for destinations based on user query"""
    # Add a short delay to simulate "thinking"
    time.sleep(0.3)
    
    # Run the search pipeline
    results = search_pipeline.run(query=query, params={"Retriever": {"top_k": top_k}})
    
    return results["documents"]

def plan_trip(query):
    """Create a trip plan based on user query"""
    print("\nSearching for the perfect destinations based on your preferences...")
    results = find_destinations(query)
    
    if not results:
        return "I couldn't find any suitable destinations for your preferences. Could you provide more details about what you're looking for?"
    
    response = "Based on your preferences, here are some recommended destinations:\n\n"
    
    for i, doc in enumerate(results, 1):
        response += f"Option {i}: {doc.meta['name']}, {doc.meta['country']}\n"
        response += f"Description: {doc.content[:200]}...\n"
        response += f"Best time to visit: {doc.meta['best_time']}\n"
        response += f"Budget range: {doc.meta['budget_range']}\n"
        response += f"Tags: {', '.join(doc.meta['tags'])}\n\n"
    
    response += "Would you like me to create a detailed itinerary for any of these destinations? If so, please specify which one and how many days you plan to stay."
    return response

def handle_itinerary_request(destination, days=3):
    """Handle a request for an itinerary"""
    return generate_itinerary(destination, days)

def main():
    print("Welcome to the Advanced Trip Planner AI!")
    print("I can help you find the perfect destination and create custom itineraries.")
    print("Tell me what you're looking for in your ideal vacation.")
    print("Type 'exit' to quit the program.")
    
    current_state = "initial"
    selected_destination = None
    
    while True:
        if current_state == "initial":
            query = input("\nWhat kind of trip are you planning? ")
            if query.lower() == 'exit':
                print("Thank you for using Advanced Trip Planner AI. Happy travels!")
                break
            
            result = plan_trip(query)
            print(result)
            current_state = "destination_suggested"
            
        elif current_state == "destination_suggested":
            query = input("\nYour response: ")
            if query.lower() == 'exit':
                print("Thank you for using Advanced Trip Planner AI. Happy travels!")
                break
            
            # Check if user is asking for an itinerary
            if "itinerary" in query.lower() or "plan" in query.lower():
                # Try to extract destination and days
                days = 3  # Default
                
                # Check for number of days
                for word in query.split():
                    if word.isdigit():
                        days = int(word)
                        break
                
                # Check for destination name
                for dest in destinations:
                    if dest["name"].lower() in query.lower():
                        selected_destination = dest["name"]
                        break
                
                if selected_destination:
                    itinerary = handle_itinerary_request(selected_destination, days)
                    print(itinerary)
                    current_state = "itinerary_provided"
                else:
                    print("I'm not sure which destination you'd like an itinerary for. Could you specify one of the destinations I suggested?")
            else:
                # Treat as a new query
                result = plan_trip(query)
                print(result)
                
        elif current_state == "itinerary_provided":
            query = input("\nWould you like to plan another trip or modify this itinerary? ")
            if query.lower() == 'exit':
                print("Thank you for using Advanced Trip Planner AI. Happy travels!")
                break
            
            if "another" in query.lower() or "new" in query.lower() or "different" in query.lower():
                current_state = "initial"
                selected_destination = None
            elif "modify" in query.lower() or "change" in query.lower():
                # Handle itinerary modification
                days = 3
                for word in query.split():
                    if word.isdigit():
                        days = int(word)
                        break
                
                itinerary = handle_itinerary_request(selected_destination, days)
                print(itinerary)
            else:
                # Treat as a new query
                result = plan_trip(query)
                print(result)
                current_state = "destination_suggested"
                selected_destination = None

if __name__ == "__main__":
    main()