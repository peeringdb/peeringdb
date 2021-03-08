# API Keys

PeeringDB offers API keys for authenticating API requests. There are two main forms of API keys:

**Organization-level API Keys**
These API keys are created and revoked from the organization admin panel. Each key gets its own custom permissions, which can be modified from the "org api key permissions" panel. Each key must have an email attached to it; this is because keys may be allowed to create and modify data in PeeringDB, and we need a contact to reach out to in case of questions.  

**User-level API Keys**
These API key are tied to a individual user account and can be created from the user profile page. There are only two permission levels: a normal key will mirror the same permissions of the user, while a readonly key will have readonly permissions to all the same namespaces as the user.

**One thing to note** is that the full api key string is only ever exposed to the user or organization at its moment of creation. If this string is lost, then the user or organization should revoke that key and create and permission a new one.

## Commandline example using Python and Requests
API keys allow developers to interact with their PeeringDB account programmatically, rather than through the website. Here is an example script in Python. It uses the module Requests to GET data about a particular Facility, and then send a PUT request to modify that data. Note that the API key is sent in the "Authorization" header, and is preceded by the text "Api-Key ".

```
import requests

API_KEY = "sample_api_key_xxxx"
URL = "https://peeringdb.com/api/fac/1"

# We set the headers to include our API key as authorization
headers = {"HTTP_AUTHORIZATION": "Api-Key " + key}

# We get data about example Facility number 1
response = response.get(URL, headers=headers)
data = response.json()

# We can print the data to inspect it, and decide what fields we want to change
print(data)

# Let's say we decide to change the name of this facility. We overwrite the value for key "name"
data["name"] = "Newly decided name"

# And then use a PUT request to send that modified data back to PeeringDB. 
# Note that this time, we must provide data to the API, using the keyword argument "data"
put_response = response.put(URL, headers=headers, data=data)

# We can print the status code to see if our request was successful.
print(put_response.status_code)

# Additionally the content of the request should include data for the now modified Facility
print(put_response.content)
```


Another note: it's best practice *not* to write your API key into your code, but rather keep API keys in separate configuration files that you then load into your script.

## Commandline example using Curl

API keys provide a cleaner way to authenticate api requests. PeeringDB recommends the commandline user creates a API_KEY variable like so
```
export API_KEY="[created api key string]"
```
then requests can be made with Curl like in the following examples:

### GET
The following request would return JSON data coresponding to the [ChiX](https://www.peeringdb.com/ix/239) Internet Exchange.
```
curl -H "Authorization: Api-Key $API_KEY" -H "Content-Type: application/json" -X GET https://peeringdb.com/api/ix/239 
```

### POST

The following request would create a new Network under the organization [United IX](https://www.peeringdb.com/org/10843). 
```
curl -H "Authorization: Api-Key $API_KEY" -H "Content-Type: application/json" -X POST --data "{\""org_id"\":\"10843\", \""name"\":\"Brand New Network\", \""asn"\":\"222\"}" https://peeringdb.com/api/net
```

### PUT

The following request would update the data about a particular Network, [ChIX Route Servers](https://www.peeringdb.com/net/7889), in particular changing the name to "Edited Name".

```
curl -H "Authorization: Api-Key $API_KEY" -H "Content-Type: application/json" -X PUT --data "{\""org_id"\":\"10843\", \""name"\":\"Edited Name\", \""asn"\":\"33713\"}" https://peeringdb.com/api/net/7889
```

### DELETE
The following request would delete the [ChiX](https://www.peeringdb.com/ix/239) Internet Exchange. The API key holder would need delete privileges to that particular Exchange.

```
curl -H "Authorization: Api-Key $API_KEY" -H "Content-Type: application/json" -X DELETE https://peeringdb.com/api/ix/239
```
