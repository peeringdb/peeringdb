/**
 * Makes a content listing sortable.
 *
 * Requirements:
 *
 *   1. jquery 1.11.3
 *   2. twentyc.core.js
 */

(function($) {

tc.u.require_namespace("twentyc.listutil");

twentyc.listutil.sortable = {
  init : function(opt) {
    if(this.initialized)
      return;
    $('[data-sort-container]').sortable(opt);
    this.initialized = true;
  },

  sorter : function(dir) {
    return this["_sort_"+dir];
  },

  natural_sorter : function(dir) {
    return this["_natural_sort_"+dir];
  },

  _sort_asc : function(a,b) {
    if(a && a.localeCompare)
      return a.localeCompare(b);

    if(a > b)
      return 1;
    if(a < b)
      return -1;
    return 0;
  },

  _sort_desc : function(a,b) {
    if(b && b.localeCompare)
      return b.localeCompare(a);

    if(a > b)
      return -1;
    if(a < b)
      return 1;
    return 0;
  },

  _natural_sort_asc : function(a,b) {
    return a.localeCompare(b, undefined, {numeric:true, sensitivity: 'base'})
  },

  _natural_sort_desc : function(a,b) {
    return b.localeCompare(a, undefined, {numeric:true, sensitivity: 'base'})
  }

}

twentyc.jq.plugin(
  "sortable",
  {
    init : function(opt) {

      this.each(function(idx) {

        var list = $(this);

        list.find("[data-sort-target]").each(function(idx) {

          var button = $(this);

          button.click(function(e) {
            list.sortable("sort", button.data("sort-target"), button);
          });

          if(button.data("sort-initial")) {
            list.sortable("sort", button.data("sort-target"), button, button.data("sort-initial"));
          }

        });


      });
      return this;

    },

    sortInitial : function() {
      this.each(function(idx) {
        var list = $(this);
        list.find("[data-sort-target]").each(function(idx) {
          var button = $(this);
          if(button.data("sort-initial")) {
            list.sortable(
              "sort",
              button.data("sort-target"),
              button,
              button.data("sort-initial"),
            );
          }
        });
      });
      return this;
    },

    sort : function(target, button, sortdir) {

      if(sortdir == undefined) {
        sortdir = button.data("sort-dir");

        if(!sortdir || sortdir == "desc")
          sortdir = "asc";
        else
          sortdir = "desc";
      }

      var sort_type = button.data("sort-type")

      if(sort_type == "natural") {
        var sorter = twentyc.listutil.sortable.natural_sorter(sortdir)
      } else {
        var sorter = twentyc.listutil.sortable.sorter(sortdir);
      }

      button.data("sort-dir", sortdir);

      this.each(function(idx) {
        var list = $(this);
        var container = list.find(list.data("sort-container")).first()

        list.find("[data-sort-target]").removeClass("sort-desc").removeClass("sort-asc");

        var rows = container.find(list.data("sort-row"));

        rows.sort(function(a,b) {
          var av = $(a).find(target).first().data("sort-value");
          var bv = $(b).find(target).first().data("sort-value");
          return sorter(av, bv);
        });

        rows.detach().appendTo(container);


      });

      button.addClass("sort-"+sortdir);

      return this;
    }
  },
  {

  }
);


})(jQuery);
