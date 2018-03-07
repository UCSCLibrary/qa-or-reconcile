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
base_url = 'http://digitalcollections-staging.library.ucsc.edu/authorities/search/'
max_results = 25

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

authority_names = {"ucsc":{"name":"UC Santa Cruz",
                  "subauthorities":{"names":"Names",
                                    "genres":"Genres",
                                    "formats":"Formats",
                                    "places":"Places",
                                    "times":"Time Periods",
                                    "subjects_all":"All Subjects",
                                    "subjects_topics":"Topical Subjects"}}}

auth_map = {"names":["locNames","gettyUlan","localNames"],
#            "genres":["locGenreForms","gettyAat","localGenres"],
            "genres":["locGenreForms","gettyAat"],
#            "formats":["gettyAat","localFormats"],
            "formats":["gettyAat"],
            "places":["geonames","locSubjects"],
#            "times":["gettyAat","localTimes"],
            "times":["gettyAat"],
#            "all_subject_headings":["locNames","locSubjects","gettyUlan","gettyAat","localTopics","localNames","localPlaces","localTimes"],
            "subjects_all":["locNames","locSubjects","gettyUlan","gettyAat","localNames"],
#            "subject_topics":["locSubjects","localTopics"]}
            "subjects_topics":["locSubjects"]}

#Map the query indexes to service types
default_query = {
    "id": "*",
    "name": "All terms",
    "index": "suggestall"
}

# Basic service metadata. There are a number of other documented options
# but this is all we need for a simple service.
def default_types(auth_names):
    types = []
    for auth_id, auth in auth_names.iteritems():
        for subauth_id, subauth_name in auth['subauthorities'].iteritems():
            type_name = auth["name"]+" "+subauth_name
            types.append({"id": subauth_id,
                          "name": type_name})
    return types
        
def upperfirst(x):
    return x[0].upper() + x[1:]

def lowerfirst(x):
    return x[0].lower() + x[1:]

def full_id(auth_name,subauth_name):
    return auth_name + upperfirst(subauth_name)

metadata = {
    "name": "UC Santa Cruz Custom Reconciliation Service",
    "defaultTypes": default_types(authority_names),
    "view": {
        "url": "{{id}}"
    }
}

def split_id(identifier):
    if not identifier:
        return "",""
    matches = re.finditer('.+?(?:(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|$)', identifier)
    split = [m.group(0) for m in matches]
    if len(split) < 2:
        return identifier, ""
    auth_name = split[0]
    if len(split) < 2:
        return identifier, identifier
    subauth_name = lowerfirst("".join(split[1:]))
    return auth_name, subauth_name


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

def search(raw_query, authtype, limit=3):
    """
    Hit the QA API for names.
    """
    out = []
    unique_ids = []
    query = text.normalize(raw_query).strip()
    match = False
    for qtype in auth_map[authtype]:
        if match: break

        auth, subauth = split_id(qtype)

        query_type_meta = [{"id": subauth, "name": authtype}]

        url = base_url+auth+"/"+subauth
        url += '?q=' + urllib.quote(query)
    
        try:
            resp = requests.get(url)
            results = json.loads(resp.text)
        except Exception as e:
            app.logger.error(e)
            sorted_out = sorted(out, key=itemgetter('score'), reverse=True)
            return sorted_out[:int(limit)]

        for position, item in enumerate(results):
            if position > max_results or match: break

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
    return sorted_out[:limit]

def reconcile_query(query, qtype = None,limit=3):
    if qtype is None:
        qtype = query.get('type')
    #authority, subauthority = split_id(qtype)
    subauthority = qtype
    query_string = query if isinstance(query,basestring) else query['query']
    app.logger.error("QUERY STRING:"+query_string)
    app.logger.error("SUBAUTHORITY:"+subauthority)
    app.logger.error("limit:"+str(limit))
    return search(query_string, subauthority, limit)

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
        # If the 'query' param starts with a "{" then it is a JSON object
        # with the search string as the 'query' member. Otherwise,
        # the 'query' param is the search string itself.
        if query.startswith("{"):
            query = json.loads(query)['query']
        limit = request.args.get("limit")
        if limit is None:
            limit = 3
        query_type = request.args.get('type', 'types')
        return jsonpify({"result": reconcile_query(query,query_type,limit)})
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
            if limit is None:
                limit = 3
            auth = query.get("type")
            if auth is None: return jsonify(metadata)
            result = reconcile_query(query,auth,limit)
            results[key] = {"result":result}
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
