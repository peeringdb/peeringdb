On `beta` environment instances it is possible to display the date when the database was last synced from the production environment. This is useful to know if the data in the beta environment is up to date with the production environment.

In order to display the correct date, either set the environment variable `DATABASE_LAST_SYNC` to a date that follows the iso8601 format (e.g., 2024-01-01T00:00:00) or run the following SQL query as part of your deploy process.


```sql
DELETE FROM peeringdb_settings WHERE setting="DATABASE_LAST_SYNC";
INSERT INTO peeringdb_settings (setting, value_str, value_bool)
VALUES ("DATABASE_LAST_SYNC",
        DATE_FORMAT(NOW(), '%Y-%m-%dT%H:%i:%S'),
        false);
```
