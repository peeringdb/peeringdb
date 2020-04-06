
{% for k, each in module.items() %}
  {% if each.db %}
    {% if each.db.name %}
create database if not exists {{env.rc.db.default.prefix}}{{each.db.name}} character set = utf8;
grant all on {{env.rc.db.default.prefix}}{{each.db.name}}.* to '{{env.rc.db.default.prefix}}{{each.name}}'@'localhost' identified by '{{each.password}}';
grant all on {{env.rc.db.default.prefix}}{{each.db.name}}.* to '{{env.rc.db.default.prefix}}{{each.name}}'@'%' identified by '{{each.password}}';
    {% endif %}

  {% for table in each.db.selectable %}
grant select on {{table}} to '{{env.rc.db.default.prefix}}{{each.name}}'@'localhost' identified by '{{each.password}}';
grant select on {{table}} to '{{env.rc.db.default.prefix}}{{each.name}}'@'%.%.int' identified by '{{each.password}}';
  {% endfor %}
  {% for table in each.db.writable %}
grant all on {{table}} to '{{env.rc.db.default.prefix}}{{each.name}}'@'localhost' identified by '{{each.password}}';
grant all on {{table}} to '{{env.rc.db.default.prefix}}{{each.name}}'@'%.%.int' identified by '{{each.password}}';
  {% endfor %}

  {% endif %}
{% endfor %}

flush privileges;

