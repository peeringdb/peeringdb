# Commands

Can be run from prod0

## undelete

First find out the version id when the object was deleted

```
python manage.py pdb_reversion_inspect <reftag> <id>
```

```
VERSION: 7 (392112) - 2018-12-24T07:13:49.612Z - User: XXX
status: 'ok' => 'deleted'
```

You want the number inside the brackets (in this case *392112*)

Then run the undelete command

```
python manage.py pdb_undelete <reftag> <id> <version id>
```

This will show you everthing that will be undeleted, it will run in pretend mode, nothing
is committed yet.

After reviewing, run the command again with the `--commit` flag

```
python manage.py pdb_undelete <reftag> <id> <version id> --commit
```
