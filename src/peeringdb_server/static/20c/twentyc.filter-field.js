/**
 * Functionality for text input fields to apply filters to
 * content
 *
 * Dependencies:
 *   1. jquery >= 1.11.13
 *   2. twentyc.core.js
 */

(function($) {

tc.u.require_namespace("twentyc.listutil");

twentyc.listutil.filter_input = {
  init : function(opt) {
    $('[data-filter-target]').filterInput(opt);
  }
}

twentyc.jq.plugin(
  "filterInput",
  {
    init : function(opt) {
      this.each(function(idx) {
        var me = $(this);

        if(!me.data("filter-initialized")) {
          // init

          var target = $(me.data("filter-target"));
          var callback = function() {
            target.trigger('filter-start')
            var n = target.children(opt.rowSelector).filterInput("test", me.val().toLowerCase());
            if(n)
              target.children(".empty-result").first().hide();
            else
              target.children(".empty-result").first().show();

            target.trigger('filter-done')
          };

          me.data("filter-callback", callback);

          me.data(
            "filter-timeout",
            new tc.u.SmartTimeout(
              callback,
              opt.interval
            )
          );

          me.keyup(function(e) {
            me.data("filter-timeout").set(callback, opt.interval);
            var target = $(me.data("filter-target"));
            target.trigger('filter-prepare', [e])
          });

          if(!target.children(".empty-result").length) {
            var erNode = $('<div class="empty-result"></div>');
            erNode.hide();
            erNode.html(opt.emptyResultMessage);
            target.prepend(erNode);
          }

          me.data("filter-initialized", true);
        }
      });

    },
    test : function(value) {
      var n = 0;
      this.each(function(idx) {
        var me = $(this);
        var myvalue = new String(me.data("filter-value"))
        var status = (value ? false : true);
        if(myvalue.length && myvalue.toLowerCase().indexOf(value) > -1) {
          status = true;
        }
        if(!status) {
          me.find('[data-filter-value]').each(function(idx_2) {
            var val = $(this).data("filter-value");
            if(typeof val == "number")
              val = ""+val;
            if(val && val.toLowerCase().indexOf(value) > -1) {
              status = true;
            }
          });
        }
        if(status) {
          me.show();
          n++;
        } else
          me.hide();

      });

      return n;

    },
    'retest' : function() {
      this.each(function(idx) {
        var me = $(this);
        var fn = me.data("filter-callback")
        fn();
      });
    }
  },
  {
    emptyResultMessage : "Nothing matched your filter",
    rowSelector : ".row",
    interval : 100
  }
);

})(jQuery);
