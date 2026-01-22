import json

def add_backlinks(ctx):
    
    eomission_vars = ctx['data']['osc:missions']
    variable_vars = ctx['data']['osc:variables']
    theme_vars = [t['id'] for themes in ctx['data']['themes'] for t in themes['concepts']]

    all_vars = [eomission_vars, variable_vars, theme_vars]
    all_paths = ['eo-missions', 'variables', 'themes']

    for vars, extension in zip(all_vars, all_paths):
        for var in vars:

            catalog_path = ctx['root'] / extension / var / 'catalog.json'
            with open(catalog_path, 'r', encoding='utf-8') as f:
                catalog = json.load(f)
            back_link_exists = any(ctx['data']['id'] in l['href'] in l['href'] for l in catalog['links'])
            
            if not back_link_exists:
                catalog['links'].append(
                    {
                        'rel': 'child',
                        'href': f'../../products/{ctx['data']['id']}/collection.json',
                        'type': 'application/json',
                        'title': 'Product: ' + ctx['data']['title']
                    }
                )
                with open(catalog_path, 'w', encoding='utf-8') as f:
                    json.dump(catalog, f, indent=2, ensure_ascii=False)