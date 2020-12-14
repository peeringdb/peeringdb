# API Keys

Peeringdb now offers API Keys for authenticating API requests. There are two main forms of API Keys:

## Organization-level API Keys
These API keys are created and revoked from the organization admin panel. Each key gets its own custom permissions, which can be modified from the "org api key permissions" panel.

## User-level API Keys
These API key are tied to a individual user account and can be created from the user profile page. There are only two permission levels: a normal key will mirror the same permissions of the user, while a readonly key will have readonly permissions to all the same namespaces as the user.

One thing to note is that the full api key string is only ever exposed to the user or organization at its moment of creation. If this string is lost, then the user or organization should revoke that key and create and permission a new one.


# Use

API keys provide a cleaner way to authenticate api requests. Peeringdb recommends the commandline user creates a API_KEY variable like so
```
export API_KEY="[created api key string]"
```
then request can be made with curl like in the following examples:
### GET
```
curl -H "Authorization: Api-Key $API_KEY" -H "Content-Type: application/json" -X GET https://peeringdb.com/api/OBJ 
```

### POST
```
curl -H "Authorization: Api-Key $API_KEY" -H "Content-Type: application/json" -X POST --data "{\""state"\":\"active\"}" https://peeringdb.com/api/OBJ
```

### PUT
```
curl -H "Authorization: Api-Key $API_KEY" -H "Content-Type: application/json" -X PUT --data "{\""state"\":\"active\"}" https://peeringdb.com/api/OBJ/42
```

### DELETE
```
curl -H "Authorization: Api-Key $API_KEY" -H "Content-Type: application/json" -X DELETE https://peeringdb.com/api/OBJ/42
```
