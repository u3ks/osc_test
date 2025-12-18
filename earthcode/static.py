import pystac
from datetime import datetime


def add_themes(collection, themes_to_add):
    '''Add themes to the collection custom fields and add links to the themes collection.'''
    
    themes_list = []
    for theme in themes_to_add:
        
        # assert theme in allowed_themes

        # add the correct link
        collection.add_link(
            pystac.Link(rel="related", 
                        target=f'../../themes/{theme}/catalog.json', 
                        media_type="application/json",
                        title=f"Theme: {theme.capitalize()}")
        )
        
        themes_list.append(
            {
                "scheme": "https://github.com/stac-extensions/osc#theme",
                "concepts": [{"id": theme}]
            }
        )

    # Add themes to the custom fields
    collection.extra_fields.update({
        "themes": themes_list
        }
    )


def add_links(collection, relations, targets, titles):

    '''Add links from the collection to outside websites.'''
    links = []
    
    for rel, target, title in zip(relations, targets, titles):
        links.append(pystac.Link(rel=rel, target=target, title=title)),
    
    collection.add_links(links)


def create_contract(name, roles, emails):
    '''Create a contact template'''
    contact =  {
        "name": name,
        "roles": [r for r in roles]
    }
    if emails:
        contact['emails'] = [{"value":email} for email in emails]
    return contact


def add_product_missions(collection, missions_to_add):
    '''Add missions to the collection custom fields and add links to the missions collection.'''
    
    for mission in missions_to_add:
        
        # add the correct link
        collection.add_link(
            pystac.Link(rel="related", 
                        target=f'../../eo-missions/{mission}/catalog.json', 
                        media_type="application/json",
                        title=f"EO Mission: {mission.capitalize()}"
            )
        )

    # Add themes to the custom fields
    collection.extra_fields.update({
            "osc:missions": missions_to_add
    }
    )


def add_product_variables(collection, variables_to_add):
    '''Add variables to the collection custom fields and add links to the missions collection.'''
    
    for variable in variables_to_add:
        
        # add the correct link
        collection.add_link(
            pystac.Link(rel="related", 
                        target=f'../../variables/{variable}/catalog.json', 
                        media_type="application/json",
                        title=f"Variable: {' '.join(s.capitalize() for s in variable.split('-')) }")
        )

    # Add themes to the custom fields
    collection.extra_fields.update({
        "osc:variables": variables_to_add
    })


def create_project_collection(project_id, 
                              project_title,
                              project_description, 
                              project_status,
                              project_license,
                              extent,
                              project_themes,
                              to_name,
                              to_email,
                              consortium_members,
                              website_link,
                              eo4socity_link=None):

    '''Create project collection template from the provided information.'''

    # Create the collection
    collection = pystac.Collection(
        id=project_id,
        description=project_description,
        extent=extent,
        license=project_license,
        title=project_title,
        extra_fields = {
            "osc:status": project_status,
            "osc:type": "project",
            "updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        },
        stac_extensions=[
            "https://stac-extensions.github.io/osc/v1.0.0/schema.json",
            "https://stac-extensions.github.io/themes/v1.0.0/schema.json",
            "https://stac-extensions.github.io/contacts/v0.1.1/schema.json"
        ]

    )

    # Add pre-determined links 
    collection.add_links([
        pystac.Link(rel="root", target="../../catalog.json", media_type="application/json", title="Open Science Catalog"),
        pystac.Link(rel="parent", target="../catalog.json", media_type="application/json", title="Projects"),
    ])

    # add the website links
    if eo4socity_link is None:
        add_links(collection, ['via', ], [website_link], ["Website"])
    else:
        add_links(collection, ['via', 'via'], [website_link, eo4socity_link], ["Website", "EO4Society Link"])

    
    # add the themes
    add_themes(collection, project_themes)

    # add the contacts
    to_contact = [(to_name, ['technical_officer'], [to_email])]
    consortium = [(cm[0], ['consoritum_member'], [cm[1]]) for cm in consortium_members]
    collection.extra_fields.update({

        "contacts": [create_contract(*info) for info in to_contact + consortium]
        
    })

    return collection


def manually_add_product_links(collection, 
                               access_link,
                               documentation_link=None,
                               item_link=None):
     # add extra links
    add_links(collection, ['via'], [access_link], ['Access'])
    if documentation_link:
        add_links(collection,  ['via'], [documentation_link], ['Documentation'])
    if item_link:
        add_links(collection,  ['child'], [item_link], ['Data collection'])


def create_product_collection(product_id, product_title, product_description, 
                              product_extent, product_license,
                              product_keywords, product_status, product_region,
                              product_themes, product_missions, product_variables,
                              project_id, project_title,
                              product_parameters=None, 
                              product_doi=None):
    '''Create a product collection template from the provided information.'''

    collection = pystac.Collection(
            id=product_id,
            title=product_title,
            description=product_description,
            extent=product_extent,
            license=product_license,
            keywords=product_keywords,
            stac_extensions=[
                "https://stac-extensions.github.io/osc/v1.0.0/schema.json",
                "https://stac-extensions.github.io/themes/v1.0.0/schema.json",
                "https://stac-extensions.github.io/cf/v0.2.0/schema.json"
            ],
        )

    # Add pre-determined links 
    collection.add_links([
        pystac.Link(rel="root", target="../../catalog.json", media_type="application/json", title="Open Science Catalog"),
        pystac.Link(rel="parent", target="../catalog.json", media_type="application/json", title="Products"),
        pystac.Link(rel="related", target=f"../../projects/{project_id}/collection.json", media_type="application/json", title=f"Project: {project_title}"),

    ])

    # Add extra properties
    collection.extra_fields.update({
        "osc:project": project_id,
        "osc:status": product_status,
        "osc:region": product_region,
        "osc:type": "product",
        "created": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
    })

    if product_doi is not None:
        collection.extra_fields["sci:doi"] = product_doi


    if product_parameters:
        collection.extra_fields["cf:parameter"] = [{"name": p} for p in product_parameters]

    add_themes(collection, product_themes)

    add_product_missions(collection, product_missions)

    add_product_variables(collection, product_variables)
    
    return collection


def create_workflow_collection(workflow_id, workflow_title, 
                               workflow_description, workflow_license,
                               workflow_keywords, workflow_formats, workflow_themes,
                               codeurl, project_id, project_title):

    '''Create a workflow collection template from the provided information.'''

    collection = {
        'id': workflow_id,
        'type': 'Feature',
        'geometry': None,
        "conformsTo": ["http://www.opengis.net/spec/ogcapi-records-1/1.0/req/record-core"],
        "properties": {
            "title": workflow_title,
            "description": workflow_description,
            "osc:type": "workflow",
            "osc:project": project_id,
            "osc:status": "completed",
            "formats": [{"name": f} for f in workflow_formats],
            "updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "created": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "keywords": workflow_keywords,
            "license": workflow_license,
            "version": "1"
        },
        "linkTemplates": [],
        "links": [
            
            {
                "rel": "root",
                "href": "../../catalog.json",
                "type": "application/json",
                "title": "Open Science Catalog"
            },            
            {
                "rel": "parent",
                "href": "../catalog.json",
                "type": "application/json",
                "title": "Workflows"
            },            

            {
                "rel": "related",
                "href": f"../../projects/{project_title}/collection.json",
                "type": "application/json",
                "title": f"Project: {project_title}"
            },
            {
                "rel": 'git',
                "href": codeurl,
                "type": "application/json",
                "title": 'Git source repository'
            }
            
        ]

    }

    collection['properties']['themes'] = [
        {
            "scheme": "https://github.com/stac-extensions/osc#theme",
            "concepts": [{"id": t} for t in workflow_themes]
        }
    ]

    for t in workflow_themes:
        collection['links'].append(
                {
                        "rel": 'related',
                        "href": f"../../{t}/land/catalog.json",
                        "type": "application/json",
                        "title": f'Theme: {t.capitalize()}'
                    }
    )
    
    return collection