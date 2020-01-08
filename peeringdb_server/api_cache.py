import os
import json
import collections

from django.conf import settings

from peeringdb_server.models import InternetExchange, IXLan, Network

import django_namespace_perms.util as nsp


class CacheRedirect(Exception):
    """
    Raise this error to redirect to cache response during viewset.get_queryset
    or viewset.list()

    Argument should be an APICacheLoader instance
    """

    def __init__(self, loader):
        super(Exception, self).__init__(self, "Result to be loaded from cache")
        self.loader = loader


###############################################################################
# API CACHE LOADER


class APICacheLoader(object):
    """
    Checks if an API GET request qualifies for a cache load
    and if it does allows you to provide the cached result
    """

    def __init__(self, viewset, qset, filters):
        request = viewset.request
        self.request = request
        self.qset = qset
        self.filters = filters
        self.model = viewset.model
        self.viewset = viewset
        self.depth = min(int(request.query_params.get("depth", 0)), 3)
        self.limit = int(request.query_params.get("limit", 0))
        self.skip = int(request.query_params.get("skip", 0))
        self.since = int(request.query_params.get("since", 0))
        self.fields = request.query_params.get("fields")
        if self.fields:
            self.fields = self.fields.split(",")
        self.path = os.path.join(
            settings.API_CACHE_ROOT,
            "%s-%s.json" % (viewset.model.handleref.tag, self.depth),
        )

    def qualifies(self):
        """
        Check if request qualifies for a cache load
        """

        # api cache use is disabled, no
        if not getattr(settings, "API_CACHE_ENABLED", False):
            return False
        # no depth and a limit lower than 251 seems like a tipping point
        # were non-cache retrieval is faster still
        if (
            not self.depth
            and self.limit
            and self.limit <= 250
            and getattr(settings, "API_CACHE_ALL_LIMITS", False) is False
        ):
            return False
        # filters have been specified, no
        if self.filters or self.since:
            return False
        # cache file non-existant, no
        if not os.path.exists(self.path):
            return False
        # request method is anything but GET, no
        if self.request.method != "GET":
            return False
        # primary key set in request, no
        if self.viewset.kwargs:
            return False

        return True

    def load(self):
        """
        Load the cached response according to tag and depth
        """

        # read cache file
        with open(self.path, "r") as f:
            data = json.load(f)

        data = data.get("data")

        # apply permissions to data
        fnc = getattr(self, "apply_permissions_%s" % self.model.handleref.tag, None)
        if fnc:
            data = fnc(data)

        # apply pagination
        if self.skip and self.limit:
            data = data[self.skip : self.skip + self.limit]
        elif self.skip:
            data = data[self.skip :]
        elif self.limit:
            data = data[: self.limit]

        return {"results": data, "__meta": {"generated": os.path.getmtime(self.path)}}

    def apply_permissions(self, ns, data, ruleset={}):
        """
        Wrapper function to apply permissions to a data row and
        return the sanitized result
        """
        if type(ns) != list:
            ns = ns.split(".")

        # prepare ruleset
        if ruleset:
            _ruleset = {}
            namespace_str = ".".join(ns)
            for section, rules in list(ruleset.items()):
                _ruleset[section] = {}
                for rule, perms in list(rules.items()):
                    _ruleset[section]["%s.%s" % (namespace_str, rule)] = perms
                    ruleset = _ruleset

        return nsp.dict_get_path(
            nsp.permissions_apply(
                nsp.dict_from_namespace(ns, data), self.request.user, ruleset=ruleset
            ),
            ns,
        )

    def apply_permissions_generic(self, data, explicit=False, join_ids=[], **kwargs):
        """
        Apply permissions to all rows according to rules
        specified in parameters

        explicit <function>

        if explicit is passed as a function it will be called and the result will
        determine whether or not explicit read perms are required for the row

        join_ids [(target_id<str>, proxy_id<str>, model<handleref>), ..]

        Since we are checking permissioning namespaces, and those namespaces may
        consist of object ids that are not necessarily in the dataset you can
        join those ids in via the join_ids parameter
        """
        rv = []

        joined_ids = collections.OrderedDict()
        e = {}
        inst = self.model()

        # perform id joining
        if join_ids:
            for t, p, model in join_ids:
                joined_ids[t] = {
                    "p": p,
                    "ids": self.join_ids(
                        data,
                        t,
                        p,
                        model,
                        list(joined_ids.get(p, e).get("ids", e).values()),
                    ),
                }

        for row in data:

            # create dict containing ids needed to build the permissioning
            # namespace
            init = dict([(k, row.get(v)) for k, v in list(kwargs.items())])

            # joined ids
            for t, j in list(joined_ids.items()):
                if j["p"] in row:
                    init[t] = j["ids"].get(row.get(j["p"]))
                elif t in joined_ids:
                    init[t] = joined_ids.get(t).get("ids").get(init[j["p"]])

            # build permissioning namespace
            ns = self.model.nsp_namespace_from_id(**init).lower()

            # apply fields filter
            if self.fields:
                for k in list(row.keys()):
                    if k not in self.fields:
                        del row[k]

            # determine whether or not read perms for this object need
            # to be explicitly set
            if explicit and callable(explicit):
                expl = explicit(row)
            else:
                expl = False

            # initial read perms check
            if nsp.has_perms(self.request.user, ns, 0x01, explicit=expl):
                ruleset = getattr(inst, "nsp_ruleset", {})

                # apply permissions to tree
                row = self.apply_permissions(ns, row, ruleset=ruleset)

                # if row still has data aftewards, append to results
                if row:
                    rv.append(row)

        return rv

    def join_ids(self, data, target_id, proxy_id, model, stash=[]):
        """
        Returns a dict mapping of (proxy_id, target_id)

        target ids are obtained by fetching instances of specified
        model that match the supplied proxy ids

        proxy ids will be gotten from data or stash

        data [<dict>, ..] list of data rows from cache load, the field
        name provided in "proxy_id" will be used to obtain the id from
        each row

        stash [<int>,..] list of ids

        if stash is set, data and proxy_field will be ignored
        """

        if stash:
            ids = stash
        else:
            ids = [r[proxy_id] for r in data]

        return dict(
            [
                (r["id"], r[target_id])
                for r in model.objects.filter(id__in=ids).values("id", target_id)
            ]
        )

    # permissioning functions for each handlref type

    def apply_permissions_org(self, data):
        return self.apply_permissions_generic(data, id="id")

    def apply_permissions_fac(self, data):
        return self.apply_permissions_generic(data, fac_id="id", org_id="org_id")

    def apply_permissions_ix(self, data):
        return self.apply_permissions_generic(data, ix_id="id", org_id="org_id")

    def apply_permissions_net(self, data):
        return self.apply_permissions_generic(data, net_id="id", org_id="org_id")

    def apply_permissions_ixpfx(self, data):
        return self.apply_permissions_generic(
            data,
            join_ids=[
                ("ix_id", "ixlan_id", IXLan),
                ("org_id", "ix_id", InternetExchange),
            ],
            ixlan_id="ixlan_id",
            id="id",
        )

    def apply_permissions_ixlan(self, data):
        return self.apply_permissions_generic(
            data,
            join_ids=[("org_id", "ix_id", InternetExchange)],
            ix_id="ix_id",
            id="id",
        )

    def apply_permissions_ixfac(self, data):
        return self.apply_permissions_generic(
            data,
            join_ids=[("org_id", "ix_id", InternetExchange)],
            ix_id="ix_id",
            id="id",
        )

    def apply_permissions_netfac(self, data):
        return self.apply_permissions_generic(
            data,
            join_ids=[("org_id", "net_id", Network)],
            net_id="net_id",
            fac_id="fac_id",
        )

    def apply_permissions_netixlan(self, data):
        return self.apply_permissions_generic(
            data,
            join_ids=[("org_id", "net_id", Network)],
            net_id="net_id",
            ixlan_id="ixlan_id",
        )

    def apply_permissions_poc(self, data):
        return self.apply_permissions_generic(
            data,
            explicit=lambda x: (x.get("visible") != "Public"),
            join_ids=[("org_id", "net_id", Network)],
            vis="visible",
            net_id="net_id",
        )
