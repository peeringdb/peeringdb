if [ -d "peeringdb_server" ]; then
  echo "Moving peeringdb migrations directory temporarily ..."
  mv peeringdb_server/migrations peeringdb_server/migrations_ignore
  echo "Fake applying NSP migrations ..."
  python manage.py migrate django_namespace_perms --fake
  echo "Applying django migrations ..."
  python manage.py migrate
  echo "Restoring peeringdb migrations directory ..."
  mv peeringdb_server/migrations_ignore peeringdb_server/migrations
  echo "Fake applying peeringdb_server migrations ..."
  python manage.py pdb_d111_migrate
  echo "Done!"
else
  echo "Script needs to be run in peeringdb project directory (same location as peeringdb_server)"
fi
