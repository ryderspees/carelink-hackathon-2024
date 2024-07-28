from flask import Flask, request, jsonify
import spacy
from spacy.matcher import Matcher
from arcgis.geocoding import geocode
from datetime import datetime, timedelta
import json
from arcgis.gis import GIS
from arcgis.features import FeatureLayer, Feature
import re
from pyproj import CRS, Transformer
import math
import os
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# Load the English language model
nlp = spacy.load("en_core_web_trf")

# Initialize the GIS
gis = GIS("https://intern-hackathon.maps.arcgis.com", os.getenv('ESRI_USER'), os.getenv('ESRI_PASS'))

def extract_location(input_string):
    doc = nlp(input_string)

    # Define relevant entity labels
    relevant_labels = ["GPE", "LOC", "ORG", "FAC", "STREET", "ADDRESS"]

    # Extract location-related entities
    location_entities = [ent.text for ent in doc.ents if ent.label_ in relevant_labels]

    # Join the extracted entities to form the specific location
    location = " ".join(location_entities)

    return location


def process_location_string(input_string):
    """
    Process the input string to extract location and get coordinates.
    """
    location = extract_location(input_string)

    if location:
        results = geocode(location)[0]
        if results:
            return {'coordinates': {'y': results['location']['y'], 'x': results['location']['x']}, 
                    'address': results['attributes']['Place_addr'],
                     'neighborhood': 'Hollywood' # results['attributes']['Nbrhd']
                     }
        else:
            return f"Could not find coordinates for '{location}'"
    else:
        return "No location found in the input string"

def categorize_input(text):
    # Process the input text
    doc = nlp(text.lower())
    
    # Initialize the matcher
    matcher = Matcher(nlp.vocab)
    
    # Define patterns for each category
    emergency_patterns = [
        [{"LOWER": {"IN": ["emergency", "urgent", "critical", "immediate"]}}]
    ]
    resource_patterns = [
        [{"LOWER": {"IN": ["food", "meal", "eat", "hungry"]}}],
        [{"LOWER": {"IN": ["shelter", "housing", "homeless", "sleep", "stay"]}}],
        [{"LOWER": {"IN": ["mental", "counseling", "therapy", "psychological"]}}],
        [{"LOWER": {"IN": ["legal", "lawyer", "attorney", "law"]}}],
        [{"LOWER": {"IN": ["clothes", "clothing", "wear", "dress"]}}],
        [{"LOWER": {"IN": ["transportation", "bus", "ride", "travel"]}}]
    ]
    sex_patterns = [
        [{"LOWER": {"IN": ["male", "man", "boy", "gentleman"]}}],
        [{"LOWER": {"IN": ["female", "woman", "girl", "lady"]}}]
    ]
    pet_patterns = [
        [{"LOWER": {"IN": ["pet", "dog", "cat", "animal"]}}]
    ]
    
    # Add patterns to the matcher
    matcher.add("EMERGENCY", emergency_patterns)
    matcher.add("RESOURCE", resource_patterns)
    matcher.add("SEX", sex_patterns)
    matcher.add("PET", pet_patterns)

    
    # Find matches in the text
    matches = matcher(doc)

    current_datetime = datetime.now()
    time_difference = timedelta(hours=4)
    new_datetime = current_datetime + time_difference
    # Initialize results
    results = {
        "emergency": "no",
        "type_of_resource": "unknown",
        "sex": "unknown",
        "pet": "no",
        "timestamp": str(new_datetime),
        "check": "no"
    }
    
    # Process matches
    for match_id, start, end in matches:
        category = nlp.vocab.strings[match_id]
        matched_text = doc[start:end].text
        
        if category == "EMERGENCY":
            results["emergency"] = "yes"
        elif category == "RESOURCE":
            if matched_text in ["food", "meal", "eat", "hungry"]:
                results["type_of_resource"] = "food"
            elif matched_text in ["shelter", "housing", "homeless", "sleep", "stay"]:
                results["type_of_resource"] = "Shelter"
            elif matched_text in ["mental", "counseling", "therapy", "psychological"]:
                results["type_of_resource"] = "mental health"
            elif matched_text in ["legal", "lawyer", "attorney", "law"]:
                results["type_of_resource"] = "legal aid"
            elif matched_text in ["clothes", "clothing", "wear", "dress"]:
                results["type_of_resource"] = "clothes"
            elif matched_text in ["transportation", "bus", "ride", "travel"]:
                results["type_of_resource"] = "transportation"
        elif category == "SEX":
            if matched_text in ["male", "man", "boy", "gentleman"]:
                results["sex"] = "male"
            else:
                results["sex"] = "female"
        elif category == "PET":
            results["pet"] = "yes"
    
    return results


def find_closest_shelter(loc_info):
    # Access the Feature Layer
    feature_layer_url = "https://services8.arcgis.com/LLNIdHmmdjO2qQ5q/arcgis/rest/services/Homeless_Shelters_and_Services/FeatureServer/0"
    feature_layer = FeatureLayer(feature_layer_url)

    # Query all features in the layer
    features = feature_layer.query(where="1=1", out_fields="*").features

    # Define the coordinate reference systems
    web_mercator = CRS.from_epsg(3857) # Web Mercator (EPSG:3857)
    wgs84 = CRS.from_epsg(4326) # WGS84 (EPSG:4326)

    # Create transformers
    web_mercator_to_wgs84 = Transformer.from_crs(web_mercator, wgs84)
    wgs84_to_web_mercator = Transformer.from_crs(wgs84, web_mercator)

    # Convert input coordinates from WGS84 to Web Mercator
    loc_x, loc_y = wgs84_to_web_mercator.transform(loc_info['y'], loc_info['x'])

    closest_distance = float('inf')
    closest_shelter_addr = None

    # Loop through the features and process their coordinate points
    for feature in features:
        # Access the geometry of the feature
        geometry = feature.geometry

        # Calculate the distance using the Euclidean distance formula in Web Mercator
        dx = geometry['x'] - loc_x
        dy = geometry['y'] - loc_y
        distance = math.sqrt(dx*dx + dy*dy)

        # Convert feature coordinates to WGS84 for printing
        lat, lon = web_mercator_to_wgs84.transform(geometry['x'], geometry['y'])

        # Check if this is the closest shelter
        if distance < closest_distance:
            closest_distance = distance
            closest_shelter_addr = feature.attributes['addrln1']

    # Convert closest_distance from Web Mercator units (meters) to kilometers
    closest_distance_km = closest_distance / 1000

    return closest_distance_km, closest_shelter_addr


def log_phone_call(loc_info):
    feature_layer_url = "https://services8.arcgis.com/LLNIdHmmdjO2qQ5q/arcgis/rest/services/Spoof_call_merged/FeatureServer/0"
    feature_layer = FeatureLayer(feature_layer_url)

    sex = "M"if loc_info['categories']['sex'] == 'male' else "F"

    new_feature = {
            'attributes': {
                'emergent': loc_info['categories']['emergency'],
                'need': loc_info['categories']['type_of_resource'],
                'sex': sex,
                'pet': loc_info['categories']['pet'],
                'responded': 1 if loc_info['categories']['check'] == "yes" else 0,
                'date_time': loc_info['categories']['timestamp'],
                'address': "Hollywood" # loc_info['location_info']['address']
            },
            'geometry': {
                'x': loc_info['location_info']['coordinates']['x'],
                'y': loc_info['location_info']['coordinates']['y'],
                'spatialReference': {'wkid': 4326}
            }
    }

    response = feature_layer.edit_features(adds=[new_feature])
    print('Feature added:', response)

def extract_phone_number(address_to_query):
    feature_layer_url = "https://services8.arcgis.com/LLNIdHmmdjO2qQ5q/arcgis/rest/services/Homeless_Shelters_and_Services/FeatureServer/0"
    feature_layer = FeatureLayer(feature_layer_url)
    query_result = feature_layer.query(where=f"addrln1 = '{address_to_query}'", out_fields="phones")
    
    # Extract the phone number from the query result
    if query_result.features:
        phone_info = query_result.features[0].attributes['phones']
        
        # Use regular expression to extract phone number and remove non-numeric characters
        phone_number_match = re.search(r'\(\d{3}\) \d{3}-\d{4}', phone_info)
        if phone_number_match:
            phone_number = phone_number_match.group(0)
            # Remove non-numeric characters
            phone_number_numeric = re.sub(r'\D', '', phone_number)
            print(f"The phone number for {address_to_query} is {phone_number_numeric}")
            return phone_number_numeric
        else:
            print(f"No phone number found in the string: {phone_info}")
    else:
        print(f"No phone number found for {address_to_query}")

@app.route('/process', methods=['POST'])
def process_input():
    data = request.json
    if not data or 'text' not in data:
        return jsonify({"error": "No input text provided"}), 400

    input_text = data['text'] + " Los Angeles"
    
    location_info = process_location_string(input_text)
    categories = categorize_input(input_text)


    print(location_info)

    loc_info = {'categories': categories, 'location_info': location_info}
    # insert call data into featurelayer
    log_phone_call(loc_info)


    # get coordinate points and addresses of all shelters
    # find closest shelter by distance
    loc_info = {'x': location_info['coordinates']['x'], 'y': location_info['coordinates']['y']}
    closest_distance, closest_shelter_addr = find_closest_shelter(loc_info)
    print(f"Closest Distance: {closest_distance} km")
    print(f"Closest Shelter: {closest_shelter_addr}")

    phone = extract_phone_number(closest_shelter_addr)

    result = {
        "address": closest_shelter_addr,
        "phone": phone,
        "type_of_resource": categories['type_of_resource']
    }
 

    print(result)


    return jsonify(result)

if __name__ == "__main__":
    app.run(debug=True)