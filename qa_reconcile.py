"""
An OpenRefine reconciliation service for the API provided by
the Questioning Authority gem 
in Samvera based digital repositories
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
import re

#For scoring results
from fuzzywuzzy import fuzz
import requests

app = Flask(__name__)

#some config
base_url = 'http://digitalcollections.library.ucsc.edu/authorities/search/'

#If it's installed, use the requests_cache library to
#cache calls to the API.
try:
    import requests_cache
    requests_cache.install_cache('qa_cache')
except ImportError:
    app.logger.debug("No request cache found.")
    pass

#Helper text processing
import text

authority_names = {"loc":{"name":"Library of Congress",
                  "subauthorities":{"names":"Names Authority",
                                    "subjects":"Subject Headings",
                                    "classification":"Classification",
                                    "childresSubjects":"Children's Subject Headings",
                                    "genreForms":"Genre/Form Terms",
                                    "performanceMediums":"Medium of Performance Thesaurus for Music",
                                    "demographicTerms":"Demographic Group Terms",
                                    "graphicMaterials":"Thesaurus for Graphic Materials",
                                    "ethnographicTerms":"Ethnographic Terms Thesaurus",
                                    "organizations":"Cultural Heritage Organizations"}},
#                                    "organizations":"Cultural Heritage Organizations",
#                                    "all":"All Available Authorities"}},
           "getty":{"name":"Getty",
                    "subauthorities":{"ulan":"Union List of Artist Names",
                                      "aat":"Art and Architecture Thesaurus",
                                      "tgn":"Thesaurus of Geographic Names",
                                      "cona":"Cultural Objects Name Authority"}},
           "geonames":{"name":"GeoNames",
                       "subauthorities":{"":""}},
           "local":{"name":"Ucsc Local",
                    "subauthorities":{"names":"Names",
                                      "topics":"Topics",
                                      "formats":"Physical Formats",
                                      "genres":"Genres / Forms"}}}

#Map the query indexes to service types
default_query = {
    "id": "*",
    "name": "All terms",
    "index": "suggestall"
}

def upperfirst(x):
    return x[0].upper() + x[1:]

def lowerfirst(x):
    return x[0].lower() + x[1:]

def full_id(auth_name,subauth_name):
    if subauth_name == "":
        return auth_name
    return auth_name + upperfirst(subauth_name)

def split_id(identifier):
    matches = re.finditer('.+?(?:(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|$)', identifier)
    split = [m.group(0) for m in matches]
    if len(split) < 2:
        return identifier, ""
    auth_name = split[0]
    subauth_name = lowerfirst("".join(split[1:]))
    return auth_name, subauth_name

def default_types(auth_names):
    types = []
    for auth_id, auth in auth_names.iteritems():
        for subauth_id, subauth_name in auth['subauthorities'].iteritems():
            type_name = auth["name"]+" "+subauth_name
            types.append({"id": full_id(auth_id,subauth_id),
                          "name": type_name})
    return types

# Basic service metadata. There are a number of other documented options
# but this is all we need for a simple service.
metadata = {
    "name": "Questioning Authority Reconciliation Service",
    "defaultTypes": default_types(authority_names),
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

def search(raw_query, auth, subauth,limit):
    """
    Hit the QA API
    """
    out = []
    unique_ids = []
    query = text.normalize(raw_query).strip()

    full_name = authority_names[auth]["name"]+" "+authority_names[auth]["subauthorities"][subauth]
    query_type_meta = [{"id": full_id(auth,subauth), "name": full_name}]

    url = base_url+auth+"/"+subauth
    url += '?q=' + urllib.quote(query)

    try:
        resp = requests.get(url)
        results = json.loads(resp.text)
    except Exception as e:
        app.logger.warning(e)
        return out
    match = False
    for position, item in enumerate(results):
        if match: break

        uri = item["id"]
        name = item["label"]

        #Avoid returning many of the
        #same result
        if uri in unique_ids:
            continue
        else:
            unique_ids.append(uri)

        score_1 = fuzz.token_sort_ratio(query, name)
        score_2 = fuzz.token_sort_ratio(raw_query, name)
        #Return a maximum score
        score = max(score_1, score_2)
        if query == text.normalize(name) or raw_query == text.normalize(name):
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
    #Refine chooses how many matches to return.
    return sorted_out[:limit]

def reconcile_query(query, qtype=None,limit=3):
    if qtype is None:
        qtype = query.get('type')
    authority, subauthority = split_id(qtype)
    query_string = query if isinstance(query,basestring) else query['query']

    return search(query_string, authority, subauthority,limit)

@app.route("/", methods=['POST', 'GET'])
def reconcile():
    #Single queries have been deprecated.  This can be removed.
    #Look first for form-param requests.
    global_limit = request.args.get('limit')
    query = request.form.get('query')

    if query is None:
        #Then normal get param.s
        query = request.args.get('query')
    if query:
        query_type = request.args.get('type', 'types')
        # If the 'query' param starts with a "{" then it is a JSON object
        # with the search string as the 'query' member. Otherwise,
        # the 'query' param is the search string itself.
        if query.startswith("{"):
            query = json.loads(query)
            global_limit = query['limit']
            query = query['query']
        return jsonpify({"result": reconcile_query(query,query_type,global_limit)})
    if global_limit is None:
        global_limit = 3
    # If a 'queries' parameter is supplied then it is a dictionary
    # of (key, query) pairs representing a batch of queries. We
    # should return a dictionary of (key, results) pairs.
    queries = request.form.get('queries')
    if queries:
        queries = json.loads(queries)
        results = {}
        for (key, query) in queries.items():
            if "limit" in query:
                limit = query['limit']
            else:
                limit = global_limit
            auth = query.get("type")
            if auth is None: return jsonify(metadata)
            result = reconcile_query(query,auth,limit)
            results[key] = {"result":result}
            app.logger.error("setting key: "+key+" with query: "+json.dumps(query))
            app.logger.error("with result: "+json.dumps(result))      
        app.logger.error("!!!! ---- results:" + json.dumps(results))
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

#
#{"q0":{"query":"Santa Cruz","limit":3},
# "q1":{"query":"United States","limit":3},
# "q2":{"query":"Wisconsin","limit":3},
# "q3":{"query":"Arkansas","limit":3},
# "q4":{"query":"Seattle","limit":3},
# "q5":{"query":"Acapulco","limit":3}}
