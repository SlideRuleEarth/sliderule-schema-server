import requests
import json
import sys

def get_dataset_metadata(short_name):
    # FIX 1: CMR is case-sensitive. Force uppercase to ensure we get all official versions.
    short_name = short_name.upper()
    
    print(f"[*] Searching CMR for dataset: {short_name}...", file=sys.stderr)
    
    # FIX 2: Request up to 50 versions so we actually have older versions to fall back on.
    col_params = {
        "short_name": short_name, 
        "page_size": 50
    }
    col_response = requests.get("https://cmr.earthdata.nasa.gov/search/collections.json", params=col_params)
    col_response.raise_for_status()
    
    entries = col_response.json().get("feed", {}).get("entry", [])
    if not entries:
        print(f"[!] Error: Could not find any collections for '{short_name}'", file=sys.stderr)
        return None
        
    def parse_version(v):
        try: return float(v.strip('vV'))
        except: return 0.0

    # Sort newest to oldest
    entries = sorted(entries, key=lambda x: parse_version(x.get("version_id", "")), reverse=True)
    print(f"[*] Found {len(entries)} dataset versions in CMR. Starting from newest...", file=sys.stderr)
    
    for collection in entries:
        concept_id = collection.get("id")
        version = collection.get("version_id", "Unknown")
        print(f"[*] Checking Concept ID: {concept_id} (Version {version})", file=sys.stderr)
        
        variables_url = "https://cmr.earthdata.nasa.gov/search/variables.umm_json"
        all_variables = []
        page_num = 1
        page_size = 2000
        
        while True:
            # FIX 3: Revert to 'concept_id'. This is the correct parameter to ask 
            # the variables endpoint for the children of a specific collection.
            var_params = {
                "concept_id": concept_id, 
                "page_size": page_size,
                "page_num": page_num
            }        
            var_response = requests.get(variables_url, params=var_params)
            
            if not var_response.ok:
                print(f"[!] API Error {var_response.status_code}: {var_response.text}", file=sys.stderr)
                var_response.raise_for_status()
            
            items = var_response.json().get("items", [])
            all_variables.extend(items)
            
            if len(items) < page_size:
                break
                
            page_num += 1

        if len(all_variables) > 0:
            print(f"[*] Success! Found {len(all_variables)} variables for Version {version}.", file=sys.stderr)
            return {
                "dataset_short_name": short_name,
                "resolved_concept_id": concept_id,
                "dataset_version": version,
                "total_fields": len(all_variables),
                "fields": all_variables
            }
            
        print(f"[!] Version {version} has 0 variables mapped in CMR. Falling back...", file=sys.stderr)

    print(f"[!] Critical Error: No versions of {short_name} have any variables mapped.", file=sys.stderr)
    return None

if __name__ == "__main__":
    # Handle the command-line argument gracefully
    DATASET_SHORT_NAME = sys.argv[1] if len(sys.argv) > 1 else "ATL06"
    
    metadata = get_dataset_metadata(DATASET_SHORT_NAME)
    
    if metadata:
        print(json.dumps(metadata, indent=2))