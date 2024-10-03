(function($) {

/**
 * twentyc.edit module that provides inline editing tools and functionality
 * for web content
 *
 * @module twentyc
 * @class editable
 * @static
 */

/// Contains several user facing validation sentences, translated

twentyc.editable = {

  /**
   * initialze all edit-enabled content
   *
   * called automatically on page load
   *
   * @method init
   * @private
   */

  init : function() {
    if(this.initialized)
      return;

    this.templates.init();

    // initialize always toggled inputs
    $('.editable.always').not(".auto-toggled").each(function(idx) {
      var container = $(this);
      container.find('[data-edit-type]').editable(
        'filter', { belongs : container }
      ).each(function(idx) {
        $(this).data("edit-always", true);
        twentyc.editable.input.manage($(this), container);
      });
    });


    $('[data-edit-target]').editable();

    // hook into data load so we can update selects with matching datasets
    $(twentyc.data).on("load", function(ev, payload) {
      $('select[data-edit-data="'+payload.id+'"]').each(function(idx) {
        $(this).data("edit-input").load(payload.data)
      });
    });

    // init modules
    $('[data-edit-module]').each(function(idx) {
      var module = twentyc.editable.module.instantiate($(this));
      module.init();
    });

    this.initialized = true;
  }
}

/**
 * humanize editable errors
 *
 * @module twentyc
 * @namespace editable
 * @class error
 * @static
 */

twentyc.editable.error = {

  /**
   * humanize the error of the specified type
   *
   * @method humanize
   * @param {String} errorType error type string (e.g. "ValidationErrors")
   * @returns {String} humanizedString
   */

  humanize : function(errorType) {
    switch(errorType) {
      case "ValidationErrors":
        return gettext("Some of the fields contain invalid values - please correct and try again.");
      break;
      case "Http403":
        return gettext("Not Allowed");
      case "Http400":
        return gettext("Bad request");
      case "Http404":
        return gettext("Not found");
      case "Http413":
        return gettext("File too large");
      case "Http500":
        return gettext("Internal error");
      case "IgnoreError":
        return "";
      default:
        return gettext("Something went wrong.");
      break;
    }
  }

}

/**
 * container for action handler
 *
 * @module twentyc
 * @namespace editable
 * @class action
 * @extends twentyc.cls.Registry
 * @static
 */

twentyc.editable.action = new twentyc.cls.Registry();

twentyc.editable.action.register(
  "base",
  {

    name : function() {
      return this._meta.name;
    },

    execute : function(trigger, container) {
      this.trigger = trigger
      this.container = container;
      if(this.loading_shim)
        this.container.children('.editable.loading-shim').show();
    },

    signal_error : function(container, error) {
      var payload = {
        reason : error.type,
        info : error.info,
        data : error.data
      }
      container.trigger("action-error", payload);
      container.trigger("action-error:"+this.name(), payload);
      $(this).trigger("error", payload);
      if(this.loading_shim)
        this.container.children('.editable.loading-shim').hide();
    },

    signal_success : function(container, payload) {
      container.trigger("action-success", payload);
      container.trigger("action-success:"+this.name(), payload);
      $(this).trigger("success", payload);
      if(this.loading_shim)
        this.container.children('.editable.loading-shim').hide();
    }
  }
);

twentyc.editable.action.register(
  "toggle-edit",
  {
    execute : function(trigger, container) {
      this.base_execute(trigger, container);
      container.editable("toggle");
      container.trigger("action-success:toggle", { mode : container.data("edit-mode") });
    }
  },
  "base"
);

twentyc.editable.action.register(
  "reset",
  {
    execute : function(trigger, container) {
      container.editable("reset");
      this.signal_success(container, {});
    }
  },
  "base"
);

twentyc.editable.action.register(
  "submit",
  {
    loading_shim : true,
    execute : function(trigger, container) {
      this.base_execute(trigger, container);

      var me = this,
          modules = [],
          targets = 1,
          changed,
          status={"error":false, "data":{}},
          i;


      var dec_targets = function(ev,data,error) {
        targets--;
        if(error)
          status.error = true;

        if(data) {
          $.extend(status.data, data);
        }

        if(!targets) {
          if(!status.error && !me.noToggle) {
            container.trigger("action-success:toggle", {mode:"view"})
            container.editable("toggle", { data:status.data });
          }

          /*
          if(!status.error && container.data("edit-always")) {
            // if container is always toggled to edit mode
            // update the original_value property of the
            // input instance, so we can properly pick up
            // changes for future edits
            container.editable("accept-values");
          }
          */

          container.editable("loading-shim", "hide");
        }
      };


      try {

        // try creating target - this automatically parses form data
        // into object literal

        var target = twentyc.editable.target.instantiate(container);
        changed = target.data._changed;

        $.extend(status.data, target.data);

        // prepare modules
        container.find("[data-edit-module]").
          //editable("filter", { belongs : container }).
          each(function(idx) {
            var module = twentyc.editable.module.instantiate($(this));
            if(!module.has_action("submit")) {
              module.prepare();
              if(module.pending_submit.length) {
                targets+=module.pending_submit.length;
                modules.push([module, $(this)])
              }
            }
          });

      } catch(error) {

        // we need to catch editable errors (identified by having type
        // set and fire off an event in case of failure - this also
        // catches validation errors

        if(error.type) {
          return this.signal_error(container, error);
        } else {

          // unknown errors are re-thrown so the browser can catch
          // them properly
          throw(error);

        }
      }

      var grouped = container.editable("filter", { grouped : true }).not("[data-edit-module]");

      grouped.each(function(idx) {
        var target = twentyc.editable.target.instantiate($(this));
        $.extend(status.data, target.data);
        if(target.data._changed) {
          targets += 1
        }
      });

      if(changed || container.data("edit-always-submit") == "yes" || container.data("edit-changed") == "yes"){


        $(target).on("success", function(ev, data) {
          me.signal_success(container, data);
          container.data("edit-changed", null);
        });
        $(target).on("error", function(ev, error) {
          me.signal_error(container, error);
          dec_targets({}, {}, true);
        });
        $(target).on("success", dec_targets);

        // submit main target
        var result = target.execute();
      } else {
        dec_targets({}, {});
      }

      // submit grouped targets

      grouped.each(function(idx) {
        var other = $(this);
        var action = new (twentyc.editable.action.get("submit"))();
        action.noToggle = true;
        $(action).on("success",dec_targets);
        $(action).on("error", function(){dec_targets({},{},true);});
        action.execute(trigger, other);
      });

      // submit modules
      for(i in modules) {
        $(modules[i][0]).on("success", dec_targets);
        $(modules[i][0]).on("error", function(){dec_targets({},{},true);});
        modules[i][0].execute(trigger, modules[i][1]);
      }

      return result;
    }
  },
  "base"
);

twentyc.editable.action.register(
  "module-action",
  {
    name : function() {
      return this.module._meta.name+"."+this.actionName;
    },
    execute : function(module, action, trigger, container) {
      this.base_execute(trigger, container);
      this.module = module;
      this.actionName = action;
      module.action = this;
      $(module.target).on("success", function(ev, d) {
        module.action.signal_success(container, d);
        $(module).trigger("success", [d]);
      });
      $(module.target).on("error", function(ev, error) {
        module.action.signal_error(container, error);
        $(module).trigger("error", [error]);
      });
      try {
        this.module["execute_"+action](trigger, container);
      } catch(error) {

        if(error.type) {
          return this.signal_error(container, error);
        } else {

          // unknown errors are re-thrown so the browser can catch
          // them properly
          throw(error);

        }

      }
    }
  },
  "base"
);

/**
 * container for module handler
 *
 * @module twentyc
 * @namespace editable
 * @class module
 * @extends twentyc.cls.Registry
 * @static
 */

twentyc.editable.module = new twentyc.cls.Registry();

twentyc.editable.module.instantiate = function(container) {
  var module = new (this.get(container.data("edit-module")))(container);
  return module;
};

/**
 * base module to use for all editable modules
 *
 * modules allow you add custom behaviour to forms / editing process
 *
 * @class base
 * @namespace twentuc.editable.module
 * @constructor
 */

twentyc.editable.module.register(
  "base",
  {
    init : function() {
      return;
    },

    has_action : function(action) {
      return this.container.find('[data-edit-action="'+action+'"]').length > 0;
    },

    base : function(container) {
      var comp = this.components = {};
      container.find("[data-edit-component]").editable("filter",{belongs:container}).each(function(idx) {
        var c = $(this);
        comp[c.data("edit-component")] = c;
      });
      this.container = container;
      container.data("edit-module-instance", this);
    },

    get_target : function(container) {
      return twentyc.editable.target.instantiate(container || this.container);
    },

    execute : function(trigger, container) {
      var action = trigger.data("edit-action");

      this.trigger = trigger;
      this.target = twentyc.editable.target.instantiate(container);

      var handler = new (twentyc.editable.action.get("module-action"))
      handler.loading_shim = this.loading_shim;
      handler.execute(this, action, trigger, container);
    },

    prepare : function() { this.prepared = true },

    execute_submit : function(trigger, container) {
      return;
    }
  }
);

/**
 * this module allows you maintain a listing of items with functionality
 * to add, remove and change the items.
 *
 * @class listing
 * @namespace twentyc.editable.module
 * @constructor
 * @extends twentyc.editable.module.base
 */

twentyc.editable.module.register(
  "listing",
  {

    pending_submit : [],

    init : function() {

      // a template has been specified for the add form
      // try to build add row form from it
      if(this.components.add && this.components.add.data("edit-template")) {
        var addrow = twentyc.editable.templates.copy(this.components.add.data("edit-template"));
        this.components.add.prepend(addrow);
      }

      if(this.container.data("edit-always")) {
        var me = this;
        this.container.on("listing:row-submit", function() {
          me.components.list.editable("accept-values");
        });
      }
    },

    prepare : function() {
      if(this.prepared)
        return;
      var pending = this.pending_submit = [];
      var me = this;
      this.components.list.children().each(function(idx) {
        var row = $(this),
            data = {};

        var changedFields = row.find("[data-edit-type]").
            editable("filter", "changed").
            editable("filter", { belongs : me.components.list }, true);

        if(changedFields.length == 0)
          return;


        row.find("[data-edit-type]").editable("filter", { belongs : me.components.list }).editable("export-fields", data);
        row.editable("collect-payload", data);
        pending.push({ row : row, data : data, id : row.data("edit-id")});
      });
      this.base_prepare();
    },

    row : function(trigger) {
      return trigger.closest("[data-edit-id]").first();
    },

    row_id : function(trigger) {
      return this.row(trigger).data("edit-id")
    },

    clear : function() {
      this.components.list.empty();
    },

    add : function(rowId, trigger, container, data) {
      var row = twentyc.editable.templates.copy(this.components.list.data("edit-template"));
      var k;
      row.attr("data-edit-id", rowId);
      row.data("edit-id", rowId);
      for(k in data) {
        row.find('[data-edit-name="'+k+'"]').each(function(idx) {
          $(this).text(data[k]);
          $(this).data("edit-value", data[k]);
        });
      }
      row.appendTo(this.components.list);
      row.addClass("newrow");
      container.editable("sync");
      if(this.action)
        this.action.signal_success(container, rowId);
      container.trigger("listing:row-add", [rowId, row, data, this]);
      this.components.list.scrollTop(function() { return this.scrollHeight; });
      return row;
    },

    remove : function(rowId, row, trigger, container) {
      row.detach();
      if(this.action)
        this.action.signal_success(container, rowId);
      container.trigger("listing:row-remove", [rowId, row, this]);
    },

    submit : function(rowId, data, row, trigger, container) {
      if(this.action)
        this.action.signal_success(container, rowId);
      container.trigger("listing:row-submit", [rowId, row, data, this]);
    },

    execute_submit : function(trigger, container) {
      var i, P;
      this.prepare();
      if(!this.pending_submit.length) {
        if(this.action)
          this.action.signal_success(container);
        return;
      }
      for(i in this.pending_submit) {
        P = this.pending_submit[i];
        this.submit(P.id, P.data, P.row, trigger, container);
      }
    },

    execute_add : function(trigger, container) {
      var data = {};
      this.components.add.editable("export", data);
      this.data = data
      this.add(null,trigger, container, data);
    },

    execute_remove : function(trigger, container) {
      var row = trigger.closest("[data-edit-id]").first();
      this.remove(row.data("edit-id"), row, trigger, container);
    }
  },
  "base"
);


/**
 * allows you to setup and manage target handlers
 *
 * @module twentyc
 * @namespace editable
 * @class target
 * @static
 */

twentyc.editable.target = new twentyc.cls.Registry();

twentyc.editable.target.error_handlers = {};

twentyc.editable.target.instantiate = function(container) {
  var handler,
      targetParam = container.data("edit-target").split(":")

  // check if specified target has a handler, if not use standard XHR hander
  if(!twentyc.editable.target.has(targetParam[0]))
    handler = twentyc.editable.target.get("XHRPost")
  else
    handler = twentyc.editable.target.get(targetParam[0])

  // try creating target - this automatically parses form data
  // into object literal
  return new handler(targetParam, container);
}

twentyc.editable.target.register(
  "base",
  {
    base : function(target, sender) {
      this.args = target;
      this.label = this.args[0];
      this.sender = sender;
      this.data = {}
      sender.editable("export", this.data)
    },
    data_clean : function(removeEmpty) {
      var i, r = {}, item;
      for(i in this.data) {
        item = this.data[i];
        if(removeEmpty && (item === null || item === "" || item === undefined))
          continue;
        if(removeEmpty && item && item.join && !item.length)
          continue;
        if(i.charAt(0) != "_")
          r[i] = this.data[i];
      }
      return r;
    },
    data_valid : function() {
      return (this.data && this.data["_valid"]);
    },
    execute : function() {}
  }
);

twentyc.editable.target.register(
  "XHRPost",
  {
    execute : function(appendUrl, context, onSuccess, onFailure) {
      var me = $(this), data = this.data;

      if(context)
        this.context = context;

      if(this.context)
        var sender = this.context;
      else
        var sender = this.sender;

      if(sender) {
        sender.editable('clear-error-popins');
      }

      $.ajax({
        url : this.args[0]+(appendUrl?"/"+appendUrl:""),
        method : "POST",
        data : this.data_clean(this.data),
        success : function(response) {
          data.xhr_response = response;
          me.trigger("success", data);
          if(onSuccess)
            onSuccess(response, data)

          if(sender && sender.data("edit-redirect-on-success")) {
            window.document.location.href = sender.data("edit-redirect-on-success");
          }

        }
      }).fail(function(response) {
        twentyc.editable.target.error_handlers.http_json(response, me, sender);
        if(onFailure)
          onFailure(response)
      });
    }
  },
  "base"
)

twentyc.editable.target.error_handlers.http_json = function(response, me, sender) {
  var info = [response.status + " " + response.statusText]
  if(response.status == 400) {
    var msg, k, i, info= [gettext("The server rejected your data")]; ///
    for(k in response.responseJSON) {
      sender.find('[data-edit-name="'+k+'"], [data-edit-error-field="'+k+'"]').each(function(idx) {
        var input = $(this).data("edit-input-instance");
        if(input) {
          msg = response.responseJSON[k];
          if(typeof msg == "object" && msg.join)
            msg = msg.join(",");
          input.show_validation_error(msg);
        }
      });
      if(k == "non_field_errors") {
        for(i in response.responseJSON[k])
          info.push(response.responseJSON[k][i]);
      }

    }
  } else if(response.status == 429) {

    info = ["Too Many Requests", response.responseJSON.message];

  } else if(response.status == 403) {

    info = ["Forbidden", response.responseJSON.message];

  } else {

    if(response.responseJSON && response.responseJSON.non_field_errors) {
      info = [];
      var i;
      for(i in response.responseJSON.non_field_errors)
        info.push(response.responseJSON.non_field_errors[i]);
    }
  }
  me.trigger(
    "error",
    {
      type : "HTTPError",
      info : info.join("<br />")
    }
  );
}

/**
 * allows you to setup and manage input types
 *
 * @module twentyc
 * @namespace editble
 * @class input
 * @static
 */

twentyc.editable.input = new (twentyc.cls.extend(
  "InputRegistry",
  {

    frame : function() {
      var frame = $('<div class="editable input-frame"></div>');
      return frame;
    },

    wire : function(it, element, container) {
      var action = container.data("edit-enter-action");
      if(it.action_on_enter && action) {
        element.on("keydown", function(e) {
          if(e.which == 13) {
            var handler = new (twentyc.editable.action.get(action));
            // handle the race condition to make sure the processed data fully generated before submitting
            setTimeout(() => {
              handler.execute(element, container);
            }, 100);
          }
        });
      }

      it.element.focus(function(ev) {
        it.reset();
      });

      if(it.wire)
        it.wire();
    },

    manage : function(element, container) {


      var it = new (this.get(element.data("edit-type")));

      it.container = container;
      it.source = element;
      it.element = element;
      it.frame = this.frame();

      it.frame.insertBefore(element);
      it.frame.append(element);

      it.original_value = it.get();

      this.wire(it, it.element, container);

      element.data("edit-input-instance", it);

      return it;
    },

    create : function(name, source, container) {

      var it = new (this.get(name));
      it.source = source
      it.container = container
      it.element = it.make();
      it.frame = this.frame();
      it.frame.append(it.element);
      it.set(source.data("edit-value"));

      it.original_value = it.get();
      it.static_elements = source.find('[data-edit-static]')
      if(source.data().hasOwnProperty("editResetValue")) {
        it.reset_value = source.data("edit-reset-value") || null;
      } else {
        it.reset_value = it.original_value;
      }

      if(it.placeholder)
        it.element.attr("placeholder", it.placeholder)
      else if(it.source.data("edit-placeholder"))
        it.element.attr("placeholder", it.source.data("edit-placeholder"))

      this.wire(it, it.element, container);

      return it;
    }
  },
  twentyc.cls.Registry
));

twentyc.editable.input.register(
  "base",
  {
    action_on_enter : false,

    set : function(value) {
      if(value == undefined) {
        this.element.val(this.source.text().trim());
      } else
        this.element.val(value);
    },

    get : function() {
      return this.element.val();
    },

    changed : function() {
      return (this.original_value != this.get());
    },

    export : function() {
      return this.get()
    },

    make : function() {
      return $('<input type="text"></input>');
    },

    blank : function() {
      return (this.element.val() === "");
    },

    validate : function() {
      return true;
    },

    validation_message : function() {
      return gettext("Invalid value") ///
    },

    required_message : function() {
      return gettext("Input required") ///
    },

    load : function() {
      return;
    },

    apply : function(value) {
      if(!this.source.data("edit-template")) {
        this.source.text(this.get());
        this.source.data("edit-value", this.get());
        if(this.static_elements) {
          this.static_elements.appendTo(this.source)
        }
      } else {
        var tmplId = this.source.data("edit-template");
        var tmpl = twentyc.editable.templates.get(tmplId);
        var node = tmpl.clone(true);
        if(this.template_handlers[tmplId]) {
          this.template_handlers[tmplId](value, node, this);
        }
        this.source.empty().append(node);
      }
    },

    show_note : function(txt, classes) {
      var note = $('<div class="editable input-note"></div>');
      note.text(txt)
      note.addClass(classes);
      if(this.element.hasClass('input-note-relative'))
        note.insertAfter(this.element);
      else
        note.insertBefore(this.element);

      this.note = note;
      return note;
    },

    close_note : function() {
      if(this.note) {
        this.note.detach();
        this.note = null;
      }
    },

    show_validation_error : function(msg) {
      this.show_note(msg || this.validation_message(), "validation-error");
      this.element.addClass("validation-error");
    },

    reset : function(resetValue) {
      this.close_note();
      this.element.removeClass("validation-error");
      if(resetValue) {
        this.source.data("edit-value", this.reset_value);
        this.set(this.reset_value);
      }
    },

    template_handlers : {}
  }
);

twentyc.editable.input.register(
  "string",
  {
    action_on_enter : true
  },
  "base"
);

twentyc.editable.input.register(
  "password",
  {
    make : function() {
      return $('<input type="password"></input>');
    },

    validate : function() {
      var conf = this.source.data("edit-confirm-with")
      if(conf) {
        return (this.container.find('[data-edit-name="'+conf+'"]').data("edit-input-instance").get() == this.get());
      } else
        return true;
    },

    validation_message : function() {
      return gettext("Needs to match password") ///
    }
  },
  "string"
);

twentyc.editable.input.register(
  "email",
  {
    placeholder : "name@example.com",

    validate : function() {
      if(this.get() === "")
        return true
      return this.get().match(/@/);
    },
    validation_message : function() {
      return gettext("Needs to be a valid email address"); ///
    },

    template_handlers : {
      "link" : function(value, node) {
        node.attr("href", "mailto:"+value).text(value);
      }
    }
  },
  "string"
);

twentyc.editable.input.register(
  "latitude",
  {
    validate : function() {
      return isFinite(this.element.val()) && Math.abs(this.element.val()) <= 90;
    },
    validation_message : function() {
      return gettext("Needs to be a valid latitude") ///
    },
    get: function() {
      return parseFloat(this.element.val()) || null;
    }
  },
  "string"
);

twentyc.editable.input.register(
  "longitude",
  {
    validate : function() {
      return isFinite(this.element.val()) && Math.abs(this.element.val()) <= 180;
    },
    validation_message : function() {
      return gettext("Needs to be a valid longitude") ///
    },
    get: function() {
      return parseFloat(this.element.val()) || null;
    }
  },
  "string"
);

twentyc.editable.input.register(
  "url",
  {
    placeholder : "http://www.example.com",
    validate : function() {
      var url = this.get()
      if(url === "")
        return true
      if(!url.match(/^[a-zA-Z]+:\/\/.+/)) {
        url = "http://"+url;
        this.set(url);
      }
      if(url.match(/\s/))
        return false;
      return true;
    },
    validation_message : function() {
      return gettext("Needs to be a valid url"); ///
    },
    template_handlers : {
      "link" : function(value, node) {
        node.attr("href", value).text(value);
      }
    }

  },
  "string"
);


twentyc.editable.input.register(
  "number",
  {
    validate : function() {
      return this.element.val().match(/^[\d\.\,-]+$/)
    },
    validation_message : function() {
      return gettext("Needs to be a number") ///
    }
  },
  "string"
);

twentyc.editable.input.register(
  "bool",
  {
    value_to_label : function() {
      return (this.element.prop("checked") ? gettext("Yes") : gettext("No")); ///
    },

    make : function() {
      return $('<input class="editable input-note-relative" type="checkbox"></input>');
    },

    get : function() {
      return this.element.prop("checked");
    },

    set : function(value) {
      if(value == true || (typeof value == "string" && value.toLowerCase() == "true"))
        this.element.prop("checked", true);
      else
        this.element.prop("checked", false);
    },

    required_message : function() {
      return "Check required"
    },

    blank : function() {
      return this.get() != true;
    },

    apply : function(value) {
      this.source.data("edit-value", this.get());
      if(!this.source.data("edit-template")) {
        this.source.text(this.value_to_label());
      } else {
        var tmplId = this.source.data("edit-template");
        var tmpl = twentyc.editable.templates.get(tmplId);
        var node = tmpl.clone(true);
        if(this.template_handlers[tmplId]) {
          this.template_handlers[tmplId](value, node, this);
        }
        this.source.empty().append(node);
      }

    }
  },
  "base"
);

twentyc.editable.input.register(
  "text",
  {
    make : function() {
      return $('<textarea></textarea>');
    }
  },
  "base"
);

twentyc.editable.input.register(
  "select",
  {
    make : function() {
      var node = $('<select></select>');
      if(this.source.data("edit-multiple") == "yes")
        node.prop("multiple", true);
      if(this.source.data("edit-data"))
        node.attr("data-edit-data", this.source.data("edit-data"))
      return node;
    },

    set : function() {
      var dataId, me = this;
      if(dataId=this.source.data("edit-data")) {
        twentyc.data.load(dataId, {
          callback : function(payload) {
            me.load(payload.data);
            me.original_value = me.get()
          }
        });
      }
    },

    value_to_label : function() {
      return $.map(
        this.element.children('option:selected'),
        function(element) {
          return $(element).text()
        }
      ).join(', ')
    },

    apply : function(value) {
      this.source.data("edit-value", this.get());
      this.source.text(this.value_to_label());
    },

    add_opt : function(id, name) {
      var opt = $('<option></option>');
      opt.val(id);
      opt.text(name);
      var value = ""+this.source.data("edit-value")
      if(this.source.data("edit-multiple") == "yes") {
        if(value && $.inArray(""+id, value.split(",")) > -1)
          opt.prop("selected", true);
      } else {
        if(id == value)
          opt.prop("selected", true);
      }
      this.finalize_opt(opt)
      this.element.append(opt);
    },

    finalize_opt : function(opt) {
      return opt;
    },

    load : function(data) {
      this.element.empty();
      if(this.source.data("edit-data-all-entry")) {
        var allEntry = this.source.data("edit-data-all-entry").split(":")
        this.add_opt(allEntry[0], allEntry[1]);
      } else {
        var allEntry = null;
      }
      var values = Object.values(data);
      if(this.source.data("edit-sorted") == "yes") {
        values.sort(
          (a, b) => a.name.localeCompare(b.name));
      }
      for(var v of values) {
        if(allEntry && allEntry[0] == v.id)
          continue;
        this.add_opt(v.id, v.name);
      }
      this.element.trigger("change");
    }
  },
  "base"
);

/**
 * class that managed DOM templates
 *
 * @class templates
 * @namespace twentyc.editable.templates
 * @static
 */

twentyc.editable.templates = {

  _templates : {},

  register : function(id, node) {
    if(this._templates[id])
      throw("Duplicate template id: "+id);
    this._templates[id] = node;
  },

  get : function(id) {
    if(!this._templates[id])
      throw("Tried to retrieve unknown template: "+id);
    return this._templates[id];
  },

  copy : function(id) {
    return this.get(id).clone().attr("id", null);
  },

  copy_and_replace : function(id, data, setEditValue) {
    var k, tmpl=this.copy(id);
    for(k in data) {
      tmpl.find('[data-edit-name="'+k+'"]').each(function() {
        $(this).text(data[k]);
        if(setEditValue)
          $(this).data("edit-value", data[k])
      });
    }
    return tmpl;
  },

  init : function() {
    if(this.initialized)
      return;

    $('#editable-templates, .editable-templates').children().each(function(idx) {
      twentyc.editable.templates.register(
        this.id,
        $(this)
      );
    });

    this.initialized = true;
  }

}

twentyc.editable.templates.register("link", $('<a></a>'));

/*
 * jQuery functions
 */

$.fn.editable = function(action, arg, dbg) {

  /******************************************************************************
   * FILTERS
   */

  if(action == "filter") {

    // filter jquery result

    var matched = [];

    if(arg) {
      // only proceed if arguments are provided
      var i = 0,
          l = this.length,
          input,
          node,
          closest

      // BELONGS (container), shortcut for first_closest:["data-edit-target", target]
      if(arg.belongs) {
        arg.first_closest = ["[data-edit-target], [data-edit-component]", arg.belongs]
      }

      // FIRST CLOSEST, first_closest:[selector, result]

      if(arg.first_closest) {
        for(; i < l; i++) {
          closest = $(this[i]).parent().closest(arg.first_closest[0]);
          if(closest.length && closest.get(0) == arg.first_closest[1].get(0))
            matched.push(this[i])
        }
      }

      // GROUPED

      else if(arg.grouped) {
        for(; i < l; i++) {
          node = $(this[i]);
          if(node.data("edit-group"))
            continue;
          $('[data-edit-group]').each(function(idx) {
            var other = $($(this).data("edit-group"));
            if(other.get(0) == node.get(0))
              matched.push(this);
          });
        }
      }

      // CHANGED FIELDS

      else if(arg == "changed") {

        for(; i < l; i++) {
          node = $(this[i]);
          input = node.data("edit-input-instance")
          if(input && input.changed()) {
            matched.push(this[i])
          }
        }

      }
    }

    return this.pushStack(matched);
  } else if(action == "export-fields") {

    // track validation errors in here
    var validationErrors = {};
    arg["_valid"] = true;

    // collect values from editable fields
    this.each(function(idx) {
      try {
        $(this).editable("export", arg)
      } catch(error) {
        if(error.type == "ValidationError") {
          validationErrors[error.field] = error.message;
          arg["_valid"] = false
        } else {
          throw(error);
        }
      }
    });
    arg["_validationErrors"] = validationErrors;

    if(!arg["_valid"]) {
      throw({type:"ValidationErrors", data:arg});
    }

  } else if(action == "collect-payload") {

    this.find(".payload").children('[data-edit-name]').each(function(idx) {
      var plel = $(this);
      arg[plel.data("edit-name")] = plel.text().trim();
    });

  }


  /******************************************************************************
   * ACTIONS
   */

  this.each(function(idx) {

    var me = $(this);

    var hasTarget = (me.data("edit-target") != null);
    var isComponent = (me.data("edit-component") != null);
    var isContainer = (hasTarget || isComponent);
    var hasAction = (me.data("edit-action") != null);
    var hasType = (me.data("edit-type") != null);

    /****************************************************************************
     * INIT
     **/

    if(!action && !me.data("edit-initialized")) {

      // mark as initialized so there is no duplicate init
      me.data("edit-initialized", true);

      // CONTAINER

      if(hasTarget) {

        if(me.hasClass("always")) {
          me.data("edit-mode", "edit");
          me.data("edit-always", true);
        } else
          me.data("edit-mode", "view");

        me.editable("sync");

        // create error message container
        var errorContainer = $('<div class="editable popin error"><div class="main"></div><div class="extra"></div></div>');
        errorContainer.hide();
        me.prepend(errorContainer)
        me.data("edit-error-container", errorContainer);

        // create loading shim
        var loadingShim = $('<div class="editable loading-shim"></div>');
        loadingShim.hide();
        me.prepend(loadingShim)
        me.data("edit-loading-shim", loadingShim);

        // whenever an action signals an error we want to update and show
        // the error container
        me.on("action-error", function(e, payload) {
          var popin = $(this).find(".editable.popin.error").editable("filter", { belongs : $(this) });
          popin.find('.main').html(twentyc.editable.error.humanize(payload.reason));
          popin.find('.extra').html(payload.info || "");
          popin.show();
          return false;
        });

      }

      // INTERACTIVE ELEMENT

      if(hasAction) {

        me.data("edit-parent", arg);

        var eventName = "click"

        if(
          me.data("edit-type") == "bool" ||
          me.data("edit-type") == "list" ||
          me.data("edit-type") == "select"
        )
        {
          eventName = "change";
        }

        // bind action event

        me.on(eventName, function() {
          var handler, a = $(this).data("edit-action");
          var container = $(this).closest("[data-edit-target]");

          /*
          if(!twentyc.editable.action.has(a)) {
            if(container.data("edit-module")) {
              handler = twentyc.editable.module.instantiate(container);
            }
            if(!handler)
              throw("Unknown action: " + a);
          } else
            handler = new (twentyc.editable.action.get(a));
          */

          if(container.data("edit-module")) {
             handler = twentyc.editable.module.instantiate(container);
          }
          if(!handler)
             handler = new (twentyc.editable.action.get(a));

          var r = handler.execute($(this), container);
          me.trigger("action:"+a, r);

        });

        me.data("edit-parent", arg);

      }

      // EDITABLE ELEMENT

      if(hasType) {

        // editable element
        me.data("edit-parent", arg);

      }

    }

    /****************************************************************************
     * RESET FORM
     */

    else if(action == "reset") {

      me.find("[data-edit-type]").
        editable("filter", { belongs : me }).
        each(function(idx) {
          $(this).data("edit-input-instance").reset(true);
        });

      me.editable("filter", {grouped:true}).not("[data-edit-module]").editable("reset");
      me.find("[data-edit-module]").editable("filter", { belongs : me }).editable("reset");
      me.find("[data-edit-component]").editable("filter", { belongs : me }).editable("reset");

    }

    /****************************************************************************
     * SYNC
     **/

    else if(action == "sync") {

      var mode = me.data("edit-mode") || "view";

      // init contained interactive elements
      me.find("[data-edit-action]").
        filter("a, input, select").
        editable("filter", {belongs:me}).
        each(function(idx) {
          var child = $(this);
          if(!child.data("edit-parent"))
            child.editable(null, me)
        });

      // init contained editable elements
      me.find("[data-edit-type]").
        editable("filter", { belongs : me }).
        each(function(idx) {
          var child = $(this);
          if(!child.data("edit-parent"))
            child.editable(null, me)
          if((child.data("edit-mode")||"view") != mode) {
            child.editable("toggle");
          }
        });

      // load required data-sets
      me.find('[data-edit-data]').
        editable('filter', { belongs : me }).
        each(function(idx) {
          var dataId = $(this).data("edit-data");
          twentyc.data.load(dataId);
        });

      // toggle mode-toggled content
      me.find('[data-edit-toggled]').
         editable('filter', { belongs : me }).
         each(function(idx) {
           var child = $(this);
           if(child.data("edit-toggled") != mode)
             child.hide()
           else
             child.show()
         });

      // sync components
      me.find('[data-edit-component]').editable("filter", { belongs : me }).each(function() {
        var comp = $(this);
        comp.data("edit-mode", mode);
        comp.editable("sync");
      });

    }

    /****************************************************************************
     * TOGGLE
     **/

    else if(action == "toggle") {

      // toggle edit mode on or off

      var mode = me.data("edit-mode")

      if(me.hasClass("always"))
        return;


      if(isContainer) {

        // CONTAINER

        if(mode == "edit") {
          me.find('[data-edit-toggled="edit"]').editable("filter", { belongs : me }).hide();
          me.find('[data-edit-toggled="view"]').editable("filter", { belongs : me }).show();
          mode = "view";

          me.removeClass("mode-edit")

          if(!arg)
            me.trigger("edit-cancel");

        } else {
          me.find('[data-edit-toggled="edit"]').editable("filter", { belongs : me }).show();
          me.find('[data-edit-toggled="view"]').editable("filter", { belongs : me }).hide();
          mode = "edit";

          me.addClass("mode-edit")
        }

        // hide pop-ins
        me.find('.editable.popin').editable("filter", { belongs : me }).hide();

        // toggled editable elements
        me.find("[data-edit-type], [data-edit-component]").editable("filter", { belongs : me }).editable("toggle", arg);

        // toggle other containers that are flagged to be toggled by this container

        me.editable("filter", { grouped : 1 }).each(function(idx) {
          $(this).editable("toggle", arg);
        });


      } else if(hasType) {

        // EDITABLE ELEMENT

        var input;

        if(me.data("editAlways"))
          return;

        if(mode == "edit") {

          // element is currently editable, switch it back to view-only
          // mode

          input = me.data("edit-input-instance")

          input.reset();

          if(arg && !$.isEmptyObject(arg.data))
            input.apply(arg.data[me.data("edit-name")])
          else
            me.html(me.data("edit-content-backup"))

            if(me.data("edit-type")==="autocomplete" && me.data("edit-keep-content")==="yes"){
              me.html(me.data("edit-content-backup"))
            }

          me.data("edit-input-instance", null);

          mode = "view";
        } else {

          // element is currently not editable, switch it to edit mode

          input = twentyc.editable.input.create(
            me.data('edit-type'),
            me,
            me.closest("[data-edit-target]")
          );

          input.element.data('edit-input', input);
          input.element.data('edit-name', me.data('edit-name'));
          input.element.data('edit-type', me.data('edit-type'));
          input.element.addClass("editable "+ me.data("edit-type"));

          // store old content so we can switch back to it
          // in case of edit-cancel event
          me.data("edit-content-backup", me.html());

          // replace content with input
          me.data("edit-input-instance", input);
          me.empty();
          me.append(input.frame);

          mode = "edit";
        }

      }

      me.data("edit-mode", mode);
      me.trigger("toggle", [mode]);

    }

    /****************************************************************************
     * TOGGLE LOADING SHIM
     **/

    else if(action == "loading-shim") {
      if(arg == "show" || arg == "hide") {
        me.children(".editable.loading-shim")[arg]();
      }
    }

    /****************************************************************************
     * REMOVE ERROR POPINS
     */

    else if(action == "clear-error-popins") {
      me.find('.editable.popin').editable("filter", { belongs : me }).hide();
    }

    /****************************************************************************
     * ACCEPT VALUES
     * This sets the original_values of all input instances within the container
     * to the current input value
     */

    else if(action == "accept-values") {
      me.find("[data-edit-type]").editable("filter", { belongs : me }).each(function() {
        var input = $(this).data("edit-input-instance");
        if(input)
          input.original_value = input.get();
      });
    }

    /****************************************************************************
     * ADD PAYLOAD
     **/

    else if(action == "payload") {

      var payload = me.children(".payload")
      if(!payload.length) {
        payload = $('<div></div>')
        payload.addClass("editable");
        payload.addClass("payload");
        me.prepend(payload);
      }

      var i, node;
      for(i in arg) {
        node = payload.children('[data-edit-name="'+i+'"]')
        if(!node.length) {
          node = $('<div></div>')
          node.attr("data-edit-name", i)
          payload.append(node);
        }
        node.text(arg[i]);
      }

    }

    /****************************************************************************
     * EXPORT FORM DATA
     **/

    else if(action == "export") {

      // export form data to object literal


      if(isContainer) {


        // container, find all inputs within, exit if not in edit mode
        if(me.data("edit-mode") != "edit" && !me.hasClass("always"))
          return;

        // export all the fields that belong to this container
        me.find('[data-edit-type]').
           editable("filter", { belongs : me }).
           editable("export-fields", arg);

        // if data-edit-id is specified make sure to copy it to exported data
        // under _id
        if(me.data("edit-id") != undefined) {
          arg["_id"] = me.data("edit-id");
        }

        // check if payload element exists, and if it does add the data from
        // it to the exported data
        me.editable("collect-payload", arg);

        me.trigger("export", [arg])

      } else if(hasType) {

        // editable element, see if input element exists and retrieve value
        var input;
        if(input=me.data("edit-input-instance")) {


          //why would this be here? breaks certain form submissions
          //by doing a premature reset - taking it out does not break any tests
          //input.reset();


          // if input is required make sure it is not blank
          if(me.data("edit-required") == "yes") {
            if(input.blank()) {
              input.show_validation_error(input.required_message());
              throw({type:"ValidationError", field:me.data("edit-name"), message:input.required_message()})
            }
          }

          // validate input
          if(!input.validate()) {
            input.show_validation_error();
            throw({type:"ValidationError", field:me.data("edit-name"), message:input.validation_message()})
          }

          arg[me.data("edit-name")] = input.export();
          if(typeof arg["_changed"] == "undefined") {
            arg["_changed"] = input.changed() ? 1: 0;
          } else {
            arg["_changed"] += input.changed() ? 1 : 0;
          }

        }
      }

    }


  });

};

/*
 * Init
 */

$(document).ready(function() {
  twentyc.editable.init();
});


})(jQuery);
