# Export Address Information Command

A Django management command that exports address information for all active organizations and facilities in PeeringDB to a CSV file.

## Overview

This command retrieves all organizations and facilities with a status of "ok" from the database and exports their address details into a CSV file. The export includes basic entity information like ID and name, along with complete address details including street address, city, state, and country information.

## Usage

```bash
python manage.py export_addresses [--output OUTPUT_FILE]
```

### Arguments

- `--output`: Optional. Specifies the output CSV file location.
  - Default value: `address_info.csv`
  - Type: String
  - Example: `--output=/path/to/export.csv`

## Output Format

The command generates a CSV file with the following columns:

- `reftag`: Entity type identifier (`org` for organizations, `fac` for facilities)
- `id`: Entity ID in the database
- `name`: Entity name
- `address1`: Primary street address
- `address2`: Secondary street address
- `suite`: Suite number
- `floor`: Floor number
- `city`: City name
- `state`: State/province name
- `zipcode`: Postal/ZIP code
- `country`: Country name

## Example Output

```csv
reftag,id,name,address1,address2,suite,floor,city,state,zipcode,country
org,1,Example Org,123 Main St,,Suite 100,4,New York,NY,10001,US
fac,1,Example DC,456 Data Center Ave,Building B,,,Dallas,TX,75001,US
```
