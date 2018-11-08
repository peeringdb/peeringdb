
# Integerating translations (Developers)

## Generate a new locale

Call makemessages and pass the locale to the `-l` option

Clone https://github.com/peeringdb/django-peeringdb somewhere
Symlink django_peeringdb in the same location as manage.py - this is so makemessages collects the locale from there as well.

```
django-admin makemessages -l de -s --no-wrap
django-admin makemessages -d djangojs -l de -s --no-wrap
```

## Updating messages in existing locale

This will add any new messages to all locale files. In other words if there has been new features added, you want to call this to make sure that their messages exist in gettext so they can be translated.

Clone https://github.com/peeringdb/django-peeringdb somewhere
Symlink django_peeringdb in the same location as manage.py - this is so makemessages collects the locale from there as well.


```
django-admin makemessages -a -s --no-wrap
django-admin makemessages -d djangojs -a -s --no-wrap
```

## Compile messages

Once translation files are ready, you need to compile them so django can use them.

```
django-admin compilemessages
```
