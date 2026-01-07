from jsonschema import validate, RefResolver
import json
from pathlib import Path
import os

SCHEMA_MAP = {
    # Generic STAC
    'catalog.json':'./schemas/catalog.json',
    'collection.json':'./schemas/collection.json',
    'record.json':'./schemas/records.json',

    # Custom Open Science Catalog (OSC) Schemas (Placeholder URLs)
    'root_catalog.json':'./schemas/catalog.json',

    "eo_mission_catalog.json": "./schemas/eo-missions/parent.json",

    "experiment_catalog.json": "./schemas/experiments/parent.json",
    "experiment_record.json": "./schemas/experiments/children.json",

    'product_catalog.json': "./schemas/products/parent.json",
    'product_collection.json': "./schemas/products/children.json",

    'project_catalog.json': "./schemas/projects/parent.json",
    'project_collection.json': "./schemas/projects/children.json",
    
    "theme_catalog.json": "./schemas/themes/parent.json",
    "variable_catalog.json": "./schemas/variables/parent.json",

    "workflow_catalog.json": "./schemas/workflows/parent.json",
    "workflow_record.json": "./schemas/workflows/children.json",

}

def determine_element_type(file_path):

    path_str = str(file_path)
    filename = file_path.name
    
    if path_str.endswith('open-science-catalog-metadata/catalog.json'):
        return f"root_{filename}"
    if "/eo-missions/" in path_str:
        return f"eo_mission_{filename}"
    if "/products/" in path_str:
        return f"product_{filename}"
    if "/projects/" in path_str :
        return f"project_{filename}"
    if "/themes/" in path_str:
        return f"theme_{filename}"
    if "/variables/" in path_str:
        return f"variable_{filename}"
    if "/workflows/" in path_str:
        return f"workflow_{filename}"
    if "/experiments/" in path_str:
        return f"experiment_{filename}"
    
    return "unknown"


def validate_relative_schema(data, schema_file):
    
    with open(schema_file) as f:
        schema = json.load(f)

    # Create a base URI for the folder containing the schema
    base_uri = Path(schema_file).absolute().parent.as_uri() + "/"
    resolver = RefResolver(base_uri=base_uri, referrer=schema)
    validate(instance=data, schema=schema, resolver=resolver)


def check_global_rules(data, root):
    errs = []
    if data.get("stac_version") not in ["1.0.0", "1.1.0"]:
        errs.append("Invalid or missing stac_version")
    
    if data.get("type") in ["Catalog", "Collection"]:
        if not data.get("title"):
            errs.append("Missing 'title' property")
            
    for link in data.get("links", []):
        if link.get("rel") in ["child", "item", "parent", "root"]:
            if "://" in link.get("href", ""):
                errs.append(f"Link {link['rel']} must be relative path")
    return errs

def check_root_catalog_rules(data, root):
    errs = []
    if data.get("id") != "osc": errs.append("Root id must be 'osc'")
    if get_link(data, "parent"): errs.append("Root catalog cannot have a parent link")
    return errs

def check_mission_rules(data, root):
    errs = []
    if not get_link(data, "via"): errs.append("Missing 'via' link")
    if not get_link(data, "parent"): errs.append("Missing 'parent' link")
    return errs

def check_product_rules(data, root):
    errs = []
    if data.get("type") != "Collection": errs.append("Product must be Collection")
    if data.get("osc:type") != "product": errs.append("osc:type must be 'product'")
    
    if not get_link(data, "via"): errs.append("Missing 'via' link")
    
    # Example of using root: Verify the referenced project exists
    project_id = data.get("osc:project")
    if not project_id:
        errs.append("Missing 'osc:project' field")
    else:
        # Check if project file exists relative to root
        project_path = root / "projects" / project_id / "collection.json"
        if not project_path.exists():
            errs.append(f"Referenced project '{project_id}' not found at {project_path}")

    check_extension(data, "osc", errs)
    return errs

def check_project_rules(data, root):
    errs = []
    if data.get("osc:type") != "project": errs.append("osc:type must be 'project'")
    
    check_extension(data, "contacts", errs)
    
    contacts = data.get("contacts", [])
    has_officer = any("technical_officer" in c.get("roles", []) for c in contacts)
    if not has_officer:
        errs.append("Missing Contact with role 'technical_officer'")
        
    return errs

def check_theme_rules(data, root):
    errs = []
    if not get_link(data, "parent"): errs.append("Missing 'parent' link")
    
    preview = get_link(data, "preview")
    if preview:
        if preview.get("type") != "image/webp":
            errs.append("Preview image must be 'image/webp'")
        if preview.get("proj:epsg") is not None:
            errs.append("Preview image proj:epsg must be null")
    return errs

def check_variable_rules(data, root):
    errs = []
    check_extension(data, "themes", errs)
    if not get_link(data, "via"): errs.append("Missing 'via' link")
    return errs

def check_workflow_rules(data, root):
    errs = []
    if data.get("type") != "Feature": errs.append("Workflow must be Feature")
    
    props = data.get("properties", {})
    if "osc:project" not in props:
        errs.append("Missing 'osc:project' in properties")
    else:
        # Check if project exists
        project_id = props["osc:project"]
        project_path = root / "projects" / project_id / "collection.json"
        if not project_path.exists():
            errs.append(f"Referenced project '{project_id}' not found")

    return errs

def check_experiment_rules(data, root):
    errs = []
    if data.get("type") != "Feature": errs.append("Experiment must be Feature")
    
    props = data.get("properties", {})
    if "osc:workflow" not in props:
        errs.append("Missing 'osc:workflow' in properties")
    return errs


def get_link(data, rel):
    for link in data.get("links", []):
        if link.get("rel") == rel:
            return link
    return None

def check_extension(data, partial_url, error_list):
    exts = data.get("stac_extensions", [])
    if not any(partial_url in e for e in exts):
        error_list.append(f"Missing required extension containing '{partial_url}'")



def validate_file(full_path):

    errors = []

    element_type = determine_element_type(Path(full_path))
    general_type = element_type.split('_')[-1]

    with open(full_path) as f:
        data = json.load(f)
    
    try:
        validate_relative_schema(data, SCHEMA_MAP.get(general_type))
    except Exception as e:
        errors.append(e)

    if element_type in ['eo_mission_catalog.json', 'variable_catalog.json', 'theme_catalog.json']:
        return errors
    
    folder_structure = str(full_path).split('/')
    root_catalog_path = '/'.join(
        f for f in folder_structure[:folder_structure.index('open-science-catalog-metadata') + 1]
    )
    root_catalog_path = Path(root_catalog_path)

    # Specific Rule Validation
    if element_type == "root_catalog.json":
        errors.extend(check_root_catalog_rules(data, root_catalog_path))

    elif element_type == "eo_mission_catalog.json":
        errors.extend(check_mission_rules(data, root_catalog_path))
        
    elif element_type == "product_collection.json":
        errors.extend(check_product_rules(data, root_catalog_path))
        
    elif element_type == "project_collection.json":
        errors.extend(check_project_rules(data, root_catalog_path))
        
    elif element_type == "theme_catalog.json":
        errors.extend(check_theme_rules(data, root_catalog_path))
        
    elif element_type == "variable_catalog.json":
        errors.extend(check_variable_rules(data, root_catalog_path))
        
    elif element_type in "workflow_record.json":
        errors.extend(check_workflow_rules(data, root_catalog_path))
        
    elif element_type in "experiment_record.json":
        errors.extend(check_experiment_rules(data, root_catalog_path))
    
    return errors

def validate_catalog(root_path):
    root = Path(root_path).resolve()
    if not root.exists():
        print(f"Error: Path {root} does not exist.")

    errors = []
    error_files = []

    # Recursive walk
    for current_dir, _, files in os.walk(root):
        for file in files:
            if file.endswith(".json"):
                
                full_path = Path(current_dir) / file
                
                file_errors = validate_file(full_path)
                
                if file_errors:
                    errors.append(file_errors)
                    error_files.append(full_path)
    
    return errors, error_files