# Questioning-Authority OpenRefine Reconciliation Endpoints
An openrefine reconcilition endpoints for use with Samvera's Questioning Authority gem. 

## What does this do?
OpenRefine has reconciliation functionality, which allows users to search external authorities for entries similar to the current input.
Questioning Authority is a gem used in Samvera based digital repositories, which gives those repositories the ability to search a variety of external authorities.
This project contains python services that connect OpenRefine's reconciliation functions to Questioning Authority's external authority searching.
There are currently two endpoints here. The "QA Reconciliation" endpoint straightforward reconciles one column in OpenRefine with one external authority supported by Questioning Authority.

The "Ucsc Reconciliation" endpoint is an attempt to allow for reconciliation of one OpenRefine column to multiple external authorities, finding the best match from all of the relevant authorities. For example, we might have a column of names that we want to reconcile from LOC names if possible, but with a few names from Getty ULAN and a few from our local database of names. It is convenient to do this in one step, and this endpoint is intended to allow for this. 
However, this does not work consistently at the moment. The QA endpoint is more consistent.

## Installation
First, the Python code in this repository must be run as a web server, either using Flask or Apache Passenger. Set the Questioning Authority url you want to use in the environment variable "QA_BASE_URL" (example: `SetEnv QA_BASE_URL http://YOUR-DOMAIN-HERE/qa/search/`). I leave this as an exercise for the reader.

Second, you must install an instance of OpenRefine, either as a shared service or locally on your own machine. The standard installation instructions for OpenRefine should work fine.

Third, in OpenRefine, create a project with some data and click the downward arrow next to the header of a column you want to reconcile. From the dropdown menu, click "Reconcile > Start Reconciling". When the reconciliation windows opens, click the "Add Standard Service" button at the bottom left, and enter the url for the python server you set up in the first installation step above. This should bring up a list of all (most) of the authority endpoints supported by Questioning Authority. Click an authority to attempt reconciliation.

## Performance Concerns and Production Environments
When reconciling large datasets, many simultaneous requests are made at once to the configured Questioning Authority endpoint. If this is part of a Samvera-based dams, the QA endpoint may be part of a live public-facing web application. It is possible that hitting it with a lot of simultanous requests could slow down the public interface for this server. If you plan to use this a lot, it is preferable to set up a dedicated instance of your repository application that is not exposed to the public but is solely responsible for reconciliation. This way you still get to use the same QA reconciliation code in OpenRefine that is used in your main application, but you won't have to stress your public-facing production application with bulk reconciliation requests. 
