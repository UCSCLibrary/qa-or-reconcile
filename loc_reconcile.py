"""
An OpenRefine reconciliation service for the API provided by
the Library of Congress.
This code is adapted from Thomson Reuters:
https://github.com/lawlesst
which drew from Michael Stephens' work:
https://github.com/mikejs/reconcile-demo
"""

from flask import Flask
from flask import request
from flask import jsonify

import json
from operator import itemgetter
import urllib
import os.path

#For scoring results
from fuzzywuzzy import fuzz
import requests

app = Flask(__name__)

#some config
base_url = 'http://id.loc.gov/search/'
max_results = 20

#If it's installed, use the requests_cache library to
#cache calls to the LOC API.
try:
    import requests_cache
    requests_cache.install_cache('loc_cache')
except ImportError:
    app.logger.debug("No request cache found.")
    pass

#Helper text processing
import text

schemes = [
    {"id":"names",
     "name":"Names Authority"},
    {"id":"subjects",
     "name":"Subject Headings"}, 
    {"id":"classification",
     "name":"Classification"}, 
    {"id":"childrenSubjects",
     "name":"Children Subject Headings"}, 
    {"id":"genreForms",
     "name":"Genre/Form Terms"}, 
    {"id":"performanceMediums",
     "name":"Medium of Performance Thesaurus for Music"}, 
    {"id":"demographicTerms",
     "name":"Demographic Group Terms"}, 
    {"id":"graphicMaterials",
     "name":"Thesaurus for Graphic Materials"}, 
    {"id":"ethnographicTerms",
     "name":"Ethnographic Terms Thesaurus"}, 
    {"id":"organizations",
     "name":"Cultural Heritage Organizations"}, 
    {"id":"all",
     "name":"All Schemes"} 
]

#Map the query indexes to service types
default_query = {
    "id": "*",
    "name": "All LCSH terms",
    "index": "suggestall"
}

# Basic service metadata. There are a number of other documented options
# but this is all we need for a simple service.
metadata = {
    "name": "LOC Reconciliation Service",
    "defaultTypes": schemes,
    "view": {
        "url": "{{id}}"
    }
}

def jsonpify(obj):
    """
    Helper to support JSONP
    """
    try:
        callback = request.args['callback']
        response = app.make_response("%s(%s)" % (callback, json.dumps(obj)))
        response.mimetype = "text/javascript"
        return response
    except KeyError:
        return jsonify(obj)

def search(raw_query, query_type="subjects"):
    """
    Hit the LOC API for names.
    """
    out = []
    unique_ids = []
    query = text.normalize(raw_query).strip()
    query_type_meta = [i for i in schemes if i['id'] == query_type]

    try:
        url = base_url + '?format=json'
        if query_type != "all":
            url += '&q=scheme:' + base_url.replace("search","authorities") + query_type
        url += '&q=' + urllib.quote(query)
        app.logger.debug("LOC API url is " + url)
        print('LOC API url is : %s' % url)
        resp = requests.get(url)
        results = json.loads(resp.text.lstrip('(').rstrip(');'))
    except Exception as e:
        app.logger.warning(e)
        return out

    match = False
    for position, item in enumerate(results):
        if position > max_results or match: break
        if not isinstance(item, list):
            continue
        if item[0] != "atom:entry":
            continue
        for position, entry in enumerate(item):
            if not isinstance(entry,list):
                continue
#            print("entry: %s",entry) 
            if entry[0] == "atom:title":
                name = entry[2];
            elif entry[0] == "atom:link":
                uri = entry[1]['href']
            elif entry[0] == "atom:id":
                item_id = entry[2]
#        uri = os.path.splitext(uri)[0] + ".json"
        uri = os.path.splitext(uri)[0]
        #Avoid returning many of the
        #same result
        if item_id in unique_ids:
            continue
        else:
            unique_ids.append(item_id)
        score_1 = fuzz.token_sort_ratio(query, name)
        score_2 = fuzz.token_sort_ratio(raw_query, name)
        #Return a maximum score
        score = max(score_1, score_2)
        if query == text.normalize(name):
            match = True
        if raw_query == text.normalize(name):
            match = True
        resource = {
            "id": uri,
            "name": name,
            "score": score,
            "match": match,
            "type": query_type_meta
        }
        out.append(resource)
    #Sort this list by score
    sorted_out = sorted(out, key=itemgetter('score'), reverse=True)
    #Refine only will handle top three matches.
    return sorted_out[:3]


@app.route("/", methods=['POST', 'GET'])
def reconcile():
    #Single queries have been deprecated.  This can be removed.
    #Look first for form-param requests.
    query = request.form.get('query')
    if query is None:
        #Then normal get param.s
        query = request.args.get('query')
        query_type = request.args.get('type', 'all')
    if query:
        # If the 'query' param starts with a "{" then it is a JSON object
        # with the search string as the 'query' member. Otherwise,
        # the 'query' param is the search string itself.
        if query.startswith("{"):
            query = json.loads(query)['query']
        results = search(query, query_type=query_type)
        return jsonpify({"result": results})
    # If a 'queries' parameter is supplied then it is a dictionary
    # of (key, query) pairs representing a batch of queries. We
    # should return a dictionary of (key, results) pairs.
    queries = request.form.get('queries')
    if queries:
        queries = json.loads(queries)
        app.logger.error("QUERIES!!! : "+json.dumps(queries))
        results = {}
        for (key, query) in queries.items():
            qtype = query.get('type')
            #If no type is specified this is likely to be the initial query
            #so lets return the service metadata so users can choose what
            # index to use.
            if qtype is None:
                return jsonpify(metadata)
            data = search(query['query'], query_type=qtype)
            results[key] = {"result": data}
        return jsonpify(results)
    # If neither a 'query' nor 'queries' parameter is supplied then
    # we should return the service metadata.
    return jsonpify(metadata)

if __name__ == '__main__':
    from optparse import OptionParser
    oparser = OptionParser()
    oparser.add_option('-d', '--debug', action='store_true', default=False)
    opts, args = oparser.parse_args()
    app.debug = opts.debug
    app.run(host='0.0.0.0', port=5002)
