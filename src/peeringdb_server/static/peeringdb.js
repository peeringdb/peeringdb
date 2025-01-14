PeeringDB = {
  // flip to false to disable js side confirmation
  // prompts
  confirmation_prompts: {
    approve : true,
    remove : true,
    deny : true
  },
  is_mobile : /Android|WebOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent),
  js_enabled : function() {
    return this.is_mobile ? false : true;
  },
  advanced_search_result : {
    net : {},
    fac : {},
    ix : {}
  },
  recaptcha_loaded : function() {
    return (typeof grecaptcha == "object");
  },

  handle_xhr_json_error : function(response, name) {
    if(response.responseJSON && response.responseJSON[name]) {
      return response.responseJSON[name]
    } else {
      return twentyc.editable.error.humanize("Http"+response.status);
    }
  },

  escape_html: function(string) {
    return String(string)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
  },

  /**
   * Renders a social media link for a given identifier and service.
   *
   * For the "website" service, it renders a link with the identifier as the href.
   * For other services, it renders a link with the identifier appended to the service URL.
   *
   * @param {string} identifier - The identifier to render (username or URL relevant to the service).
   * @param {string} service - The service to render the identifier for.
   * @returns {object} The jQuery node for the rendered link.
   */
  social_media_link: function(identifier, service) {
    if (service === "website") {
      return $('<a/>').attr('href', identifier).text(identifier);
    }
    if (service === "facebook") {
      return $('<a/>').attr('href', 'https://www.facebook.com/' + identifier).text(identifier);
    }
    if (service === "x") {
      return $('<a/>').attr('href', 'https://x.com/' + identifier).text(identifier);
    }
    if (service === "instagram") {
      return $('<a/>').attr('href', 'https://www.instagram.com/' + identifier).text(identifier);
    }
    if (service === "linkedin") {
      return $('<a/>').attr('href', 'https://www.linkedin.com/company/' + identifier).text(identifier);
    }
    if (service === "tiktok") {
      return $('<a/>').attr('href', 'https://www.tiktok.com/@' + identifier).text(identifier);
    }

    return $('<span/>').text(identifier);
  },

  init : function() {
    this.InlineSearch.init_search();

    twentyc.listutil.filter_input.init();
    twentyc.listutil.sortable.init();

    this.csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;
    $.ajaxSetup({
      beforeSend : function(xhr, settings) {
        if(!/^(GET|HEAD|OPTIONS|TRACE)$/.test(settings.type) && !this.crossDomain) {
          xhr.setRequestHeader("X-CSRFToken", PeeringDB.csrf);
        }
      }
    });

    $('#form-create-account').on('export', function(e, data) {
      if(this.recaptcha_loaded()){
        data.recaptcha = grecaptcha.getResponse();
      } else {
        data.captcha = $('#id_captcha_generator_0').val()+":"+$('#id_captcha_generator_1').val()
      }
    }.bind(this));

    setTimeout(function() {
      var fallback = $('#form-create-account').find('.fallback');
      if(!this.recaptcha_loaded()) {
        console.log("re-captcha could not be loaded, falling back to internal captcha");
        $('#form-create-account').find('.recaptcha').hide();
        fallback.show();
      } else {
        // since re-captcha loaded successfully we don't need a requirement
        // on the fallback input
        fallback.find('#id_captcha_0').attr('required', false);
      }
    }.bind(this), 3000);

    this.fix_list_offsets();

    $('.sponsor-badge').click(function(e) {
      // only redirect while not in edit mode
      if($(this).parents('.mode-edit').length == 0)
        window.location.href = "/sponsors";
    });


    $('.translate-btn').click(function(e){
      $(this).closest('.fmt_text').find('.popin').remove();
      var note_o = $(this).closest('.fmt_text').find('p');
      var ps = [];
      note_o.each(function(i,o){
        ps.push($(o).text());
      });
      var note = ps.join(' xx22xx ');
      var source = ''; //$('select[name="language-to"]').val();
      var tgt = ''; //$('select[name="language-to"]').val();
      $.post('translate', 'note=' + note + '&target=' + tgt + '&source=' + source)
       .done(function(reply){
          if('undefined' != typeof(reply.error)){
              var message = ('undefined' != typeof(reply.error.error))? reply.error.error.message : JSON.stringify(reply.error);
              note_o.parent().append( '<div class="editable popin error">' + message + '</div>')
              return;
          }
          if('undefined' == typeof(reply.translation) || 'undefined' == typeof(reply.translation.translatedText)){
              note_o.parent().append( '<div class="editable popin error">Unknown error</div>')
              return;
          }
          var translation = reply.translation.translatedText.split(' xx22xx ').join('</p><p>');
          note_o.parent().append( '<div class="editable popin info"><p>' + translation + '</p></div>')
       })
       .fail(function(a,b,c){
         console.log(a,b,c);
       });
    });

    // render markdown content
    $('[data-render-markdown="yes"]').each(function() {
      var converter = new showdown.Converter({openLinksInNewWindow: 'true'})
      var value = $(this).data("edit-value")
      // sanitize any html tags
      var translate = $(this).find('div.translate').detach()

      var html = converter.makeHtml(value.replace(/>/g, '&gt;').replace(/</g, '&lt;'))
      // set html after further sanitizing output via DOMPurify
      $(this).html(DOMPurify.sanitize(html, {
        SAFE_FOR_JQUERY: true,
        ADD_ATTR: ['target'],
      }))
      $(this).append(translate);
    });

  },

  focus: function() {
    // autofocus fields
    var path = window.location.pathname;
    if (path == '/') {
      $("#search").focus();
    }
    else if (path == '/advanced_search') {
      $(".tab-pane.active").find("input.editable")[0].focus()
    }
  },

  // fix list x offsets depending on whether content is overflowing
  // or not - as it gets pushed over by scrollbars
  fix_list_offsets : function() {
    $('.scrollable').each(function() {
      if(this.clientHeight >= this.scrollHeight && $(this).children().length>1) {
        $(this).find(".empty-result").css("margin-right", "-15px");
      } else {
        $(this).css("padding-right", "");
        $(this).find(".empty-result").css("margin-right", "");
      }
    });
  },

  // some api listings have an external form to create new items
  // this function takes care of linking the form up with the listing
  // module
  list_ext_add : function(form, listing) {
    form.on('action-success:submit', function(ev, data) {
      var instance = listing.data('edit-module-instance')
      instance.listing_add(
        data.id,
        $(this),
        instance.container,
        data
      )
      // clear any error popins on form
      $(this).editable('clear-error-popins');
      // reset the form
      $(this).editable('reset');
    });
  },

  pretty_speed : function(value) {
    value = parseInt(value);
    if(value >= 1000000)
      value = (value / 1000000)+"T";
    else if(value >= 1000)
      value = (value / 1000)+"G";
    else
      value = value+"M";
    return value
  },

  // if an api response includes a "geovalidation warning"
  // field in its metadata, display that warning

   add_geo_warning : function(meta, endpoint) {
    $('.geovalidation-warning').each(function(){
      let popin = $(this);
      let warning = meta.geovalidation_warning;
      if (endpoint == popin.data("edit-geotag")){
        popin.text(warning);
        popin.removeClass("hidden").show();

      }
    })
   },

   // if an api response includes a "geo"
   add_suggested_address : function(request, endpoint) {

    let popin = $('.suggested-address').filter(function() {
      return $(this).data("edit-geotag") == endpoint
    });
    if (popin === null){
      return
    }

    // Fill in text to each field
    let suggested_address = request.meta.suggested_address;
    let address_fields = popin.find('div, span').filter(function(){
      return $(this).data("edit-field")
    })
    address_fields.each(function(){
      let elem = $(this);
      let field = elem.data("edit-field");
      let value = suggested_address[field];
      if (value){
        if (field === "city" || field === "state"){
          value += ",";
        }
        elem.text(value);
      }

    })

    // Initialize the Submit button
    let button = popin.find("a.btn.suggestion-accept");
    PeeringDB.init_accept_suggestion(button, request, endpoint);

    // Dismiss suggestion button
    let dismiss_button = popin.find("a.btn.suggestion-dismiss");
    dismiss_button.click(() => popin.addClass("hidden").hide())

    // Show the popin
    popin.removeClass("hidden").show();
   },

  // initializes the "Accept suggestion" button

  init_accept_suggestion : function(button, response, endpoint){

    let payload = response.data[0];
    // Overwrite returned instance with the suggested data
    Object.assign(payload, response.meta.suggested_address);

    // No need to have latitude or longitude
    // in the payload since it will get
    // geocoded again

    delete payload.latitude;
    delete payload.longitude;


    // Set up PUT request on click
    button.click(function(event){
      $("#view").editable("loading-shim", "show");
      PeeringDB.API.request(
        "PUT",
        endpoint,
        payload.id,
        payload,
        function(){
          PeeringDB.refresh()
        }
      )
    });

  },
  // searches the page for all editable forms that
  // have data-check-incomplete attribute set and
  // displays a notification if any of the fields
  // are blank

  incomplete_data_notify : function() {
    $('[data-check-incomplete="Yes"]').each(function() {
      var status = { incomplete : false};
      $(this).find('[data-edit-name]').each(function() {
        var value = $(this).html().trim();
        var field = $(this).prev('.view_field');
        var group = field.data("notify-incomplete-group")

        if(!field.length)
          field = $(this).parent().prev('.view_field');

        // if field is part of a notify-incomplete-group
        // it means we don't want to show a warning as long
        // as one of the members of the group has it's value set

        if(group && (value == "" || value == "0")) {
          var other, i, others, _value;

          // get other members of the group

          others = $('[data-notify-incomplete-group="'+group+'"]')

          for(i = 0; i < others.length; i++) {
            other = $(others[i]).next('.view_value')
            _value = other.html().trim()

            // other group member's value is set, use that value
            // to toggle that we do not want to show a notification
            // warning for this field

            if(_value != "" && _value != "0") {
              value = _value
              break;
            }
          }
        }

        var check = (field.find('.incomplete').length == 1);
        if(check && (value == "" || value == "0")) {
          status.incomplete = true;
          field.find('.incomplete').removeClass("hidden")
        } else {
          field.find('.incomplete').addClass("hidden")
        }
      })

      if(status.incomplete) {
        $(this).find('.editable.popin.incomplete').removeClass("hidden").show();
      } else {
        $(this).find('.editable.popin.incomplete').addClass("hidden").hide();
      }
    });
  },

  /**
   * prompt user with a confirmation dialogue
   *
   * will take `confirmation_prompts` setting into account
   */

  confirm: function(msg, type) {
    if(!type || this.confirmation_prompts[type]) {
      return confirm(msg);
    } else {
      return true;
    }
  },

  refresh: function() {
    window.document.location.href = window.document.location.href;
  }

}

function moveCursorToEnd(el) { // lgtm[js/unused-local-variable]
    if (typeof el.selectionStart == "number") {
        el.selectionStart = el.selectionEnd = el.value.length;
    } else if (typeof el.createTextRange != "undefined") {
        el.focus();
        var range = el.createTextRange();
        range.collapse(false);
        range.select();
    }
}

/**
 * Tools to handle pre and post processing of ix/net/fac/org views
 * submissions
 * @class ViewTools
 * @namespace PeeringDB
 */


PeeringDB.ViewTools = {

  /**
   * applies the value of a field as it was returned by the
   * server in the response to the submissions to the corresponding
   * form element on the page
   *
   * this only needs to be done for fields that rely on server side
   * data validation that can't be done locally
   *
   * @method apply_data
   * @param {jQuery} container - main js-edit element for the submissions
   * @param {Object} data - object literal containing server response for the entity
   * @param {String} field - field name
   */

  apply_data : function(container, data, field) {

    var input;
    input = $('[data-edit-name="'+field+'"]').data("edit-input-instance")
    if(input) {
      input.set(data[field]);
      input.apply(data[field]);
    }
  },

  /**
   * after submission cleanup / handling
   *
   * @method after_submit
   * @param {jQuery} container - main js-edit element for the submissions
   * @param {Object} data - object literal containing server response for the entity
   */

  after_submit : function(container, data) {

    const addressFields = ["address1", "address2", "city", "state", "zipcode", "geocode"];
    var target = container.data("edit-target");

    if(target == "api:ix:update") {
      this.apply_data(container, data, "tech_phone");
      this.apply_data(container, data, "policy_phone");
    }
    if (target === "api:fac:update" || target === "api:org:update") {
      addressFields.forEach(field => this.apply_data(container, data, field));
      this.update_geocode(data);
    }
    if (target == "api:net:update") {

      // check if "allow-ixp-update" option was turned a complete reload of the view is needed
      var orig_data = $('[data-edit-name=allow_ixp_update]').data("edit-content-backup");
      if(data.allow_ixp_update && orig_data.match(/checkmark-off.png/)) {
        PeeringDB.refresh();
      }

      return;
    }
    if (target == "api:fac:update") {

      // on facility `region_continent` is read-only and determined
      // from the country during the save so we need to update it manually
      // when the data comes back from the api

      $('[data-edit-name="region_continent"]').
        data("edit-value", data.region_continent).
        text(data.region_continent);
    }
  },

  update_geocode: function(data){
    const geo_field = $("#geocode_active");
    if (data.latitude && data.longitude){
      let link = `https://maps.google.com/?q=${data.latitude},${data.longitude}`
      let contents = `<a href="${link}">${data.latitude}, ${data.longitude}</a>`
      geo_field.empty().append(contents);
      $("#geocode_inactive").addClass("hidden").hide();
    } else if (data.latitude === null && data.longitude === null) {
      $("#geocode_active").empty();
      $("#geocode_inactive").removeClass("hidden").show();
    }
  }
}


PeeringDB.ViewActions = {

  init : function() {
    $('[data-view-action]').each(function(){
      $(this).click(function() {
        var action = $(this).data("view-action");
        var id = $(this).closest("[data-edit-id]").data("edit-id");
        PeeringDB.ViewActions.actions[action](id, $(this));
      });
    });
  },

  actions : {}
}

PeeringDB.ViewActions.actions.ix_ixf_preview = function(netId) {
  $("#ixf-preview-modal").modal("show");
  var preview = new PeeringDB.IXFPreview()
  preview.request(netId, $("#ixf-log"));
}


PeeringDB.ViewActions.actions.ix_ixf_request_import = function(ixId) {
  var button =  $('[data-view-action="ix_ixf_request_import"]')
  button.attr("title","").tooltip("hide").attr("data-trigger", "manual");
  $.post(`/api/ix/${ixId}/request_ixf_import`).done(
    () => {
      $('.ixf-import-request-status').addClass("alert alert-warning").text(gettext("Queued"))
    }
  ).fail(
    (response,typ,msg) => {
      if(response.status == 429) {
        let seconds = response.responseJSON.meta.error.match(/(\d+)/)[0]
        button.attr('title', gettext("Please wait before requesting another import.")+" "+gettext("Available in: ")+seconds+" "+gettext("seconds")).tooltip("show");
      } else {
        button.attr('title',msg).tooltip("show");
      }
    }
  );
}


PeeringDB.ViewActions.actions.net_ixf_preview = function(netId) {
  $("#ixf-preview-modal").modal("show");
  var preview = new PeeringDB.IXFNetPreview()
  preview.request(netId, $("#ixf-log"));
}

PeeringDB.ViewActions.actions.net_ixf_postmortem = function(netId) {
  $("#ixf-postmortem-modal").modal("show");
  var postmortem = new PeeringDB.IXFNetPostmortem()
  postmortem.request(netId, $("#ixf-postmortem"));
}

PeeringDB.ViewActions.actions.fac_approve_carrier = function(carrierfac_id, button) {
  $.post(`/api/carrierfac/${carrierfac_id}/approve`).done(
    () => {
      button.tooltip("hide");
      button.siblings(".btn-danger").detach();
      button.detach();
    }
  ).fail(
    () => { button.attr('title',msg).tooltip("show") }
  );
}

PeeringDB.ViewActions.actions.fac_reject_carrier = function(carrierfac_id, button) {
  $.post(`/api/carrierfac/${carrierfac_id}/reject`).done(
    () => {
      button.tooltip("hide");
      button.closest("div.row").detach();
    }
  ).fail(
    () => { button.attr('title',msg).tooltip("show") }
  );
}

/**
 * Handles the IX-F proposals UI for suggestions
 * made to networks from exchanges through
 * the exchange's IX-F data feeds
 * @class IXFProposals
 * @namespace PeeringDB
 * @constructor
 */

PeeringDB.IXFProposals = twentyc.cls.define(
  "IXFProposals",
  {
    IXFProposals : function() {

      var ixf_proposals = this;

      // the netixlan list element in the network
      // view (Public peering exchange points)
      this.netixlan_list = $('[data-edit-target="api:netixlan"]')

      // the netixlan list module
      this.netixlan_mod = this.netixlan_list.data('editModuleInstance')

      // this will be true once the user as applied or dismissed
      // a suggestion. If true once the network editor is closed
      // either through cancel or save a page reload will be forced
      this.require_refresh= false;

      // wire button to reset dismissed proposals
      $('#btn-reset-proposals').click(function() {
        ixf_proposals.reset_proposals($(this).data("reset-path"))
      });

      // process and wire all proposals (per exchange)
      $("[data-ixf-proposals-ix]").each(function() {
        // individual exchange

        // container element for proposals
        var proposals = $(this)

        // wire batch action buttons
        var button_add_all = proposals.find('button.add-all')
        var button_resolve_all = proposals.find('button.resolve-all');

        button_add_all.click(() => { ixf_proposals.add_all(proposals); });
        button_resolve_all.click(() => { ixf_proposals.resolve_all(proposals); });

        ixf_proposals.sync_proposals_state(proposals);

        // wire proposals
        proposals.find('.row.item').each(function() {
          var row = $(this)
          var button_add = row.find('button.add');
          var button_dismiss = row.find('button.dismiss');
          var button_delete = row.find('button.delete')
          var button_modify = row.find('button.modify')

          button_add.click(() => { ixf_proposals.add(row) })
          button_dismiss.click(() => { ixf_proposals.dismiss(row) })
          button_delete.click(() => {
            if(!PeeringDB.confirm(button_delete.data("confirm")))
              return
            ixf_proposals.delete(row)
          })
          button_modify.click(() => { ixf_proposals.modify(row) })
        })
      })
    },

    /**
     * Sends ajax request to reset dismissed proposals
     * and upon success will force a page reload
     * @method reset_proposals
     * @param {String} path url path to reset proposals
     */

    reset_proposals : function(path) {
      $.ajax({
        method: "POST",
        url: path
      }).done(PeeringDB.refresh);
    },

    /**
     * Dismisses a proposal
     * @method dismiss
     * @param {jQuery} row jquery result for proposal row
     */

    dismiss : function(row) {
      var data= this.collect(row);
      row.find('.loading-shim').show();
      $.ajax({
        method: "POST",
        url: "/net/"+data.net_id+"/dismiss-ixf-proposal/"+data.suggestion_id+"/",
        data: {}
      }).
      fail((response) => { this.render_errors(row, response); }).
      done(() => { this.detach_row(row);}).
      always(() => {
        row.find('.loading-shim').hide();
      })
    },

    /**
     * Apply modifications to netixlan form in
     * public peering exchange points list
     * from proposal row
     * @method modify
     * @param {jQuery} row jquery result for proposal row
     */

    modify : function(row) {
      var data=this.collect(row);
      var proposals = row.closest("[data-ixf-proposals-ix]")
      var ixf_proposals = this;

      var requirements = row.find("[data-ixf-require-delete]")

      var apply = () => {
        var netixlan_row = this.netixlan_list.find('[data-edit-id="'+data.id+'"]')
        netixlan_row.find('[data-edit-name="speed"] input').val(data.speed)
        netixlan_row.find('[data-edit-name="ipaddr4"] input').val(data.ipaddr4)
        netixlan_row.find('[data-edit-name="ipaddr6"] input').val(data.ipaddr6)
        netixlan_row.find('[data-edit-name="is_rs_peer"] input').prop("checked", data.is_rs_peer)
        netixlan_row.find('[data-edit-name="operational"] input').prop("checked", data.operational)
        netixlan_row.addClass("newrow")
        this.detach_row(row);
        row.find('button').tooltip("hide")
      }


      if(!requirements.length)
        return apply();

      var promise = new Promise((resolve, reject) => { resolve(); });

      requirements.each(function() {
        var req_id = $(this).data("ixf-require-delete")
        promise.then(ixf_proposals.delete(
          proposals.find('.suggestions-delete [data-ixf-id="'+req_id+'"]')
        ))
      });

      promise.then(apply)
    },

    /**
     * Applies a proposed netixlan deletion
     * @method delete
     * @param {jQuery} row jquery result for proposal row
     */

    delete : function(row) {
      var data=this.collect(row);
      row.find('.loading-shim').show();

      return PeeringDB.API.request(
        "DELETE",
        "netixlan/"+data.id,
        0,
        {}
      ).fail(
        (response) => { this.render_errors(row, response); }
      ).done(
        () => {
          this.netixlan_list.find('[data-edit-id="'+data.id+'"]').detach();
          this.detach_row(row);
        }
      ).always(() => {
        row.find('.loading-shim').hide();
      })

    },

    /**
     * Batch applies all netixlan creations
     * @method add_all
     * @param {jQuery} jquery result for exchange proposals container
     */

    add_all : function(proposals) {

      var entries = this.all_entries_for_action(proposals, "add");

      if(!entries.rows.length)
        return alert(gettext("Nothing to do"))

      var confirm_text = [
        gettext("This will create the following entries")
      ]

      var b = PeeringDB.confirm(
        confirm_text.concat(entries.ixf_ids).join("\n")
      )

      if(b)
        this.process_all_for_action(entries.rows, "add");
    },

    /**
     * Batch applies all netixlan modifications and removals
     * @method resolve_all
     * @param {jQuery} jquery result for exchange proposals container
     */

    resolve_all : function(proposals) {

      var entries_delete = this.all_entries_for_action(proposals, "delete")
      var entries_modify = this.all_entries_for_action(proposals, "modify")

      var confirm_text = []

      if(!entries_delete.rows.length && !entries_modify.rows.length) {
        alert(gettext("Nothing to do"))
        return;
      }

      if(entries_delete.rows.length) {
        confirm_text.push(gettext("Remove these entries"))
        confirm_text = confirm_text.concat(entries_delete.ixf_ids)
        confirm_text.push("")
      }

      if(entries_modify.rows.length) {
        confirm_text.push(gettext("Update these entries"))
        confirm_text = confirm_text.concat(entries_modify.ixf_ids)
        confirm_text.push("")
      }

      var b = PeeringDB.confirm(confirm_text.join("\n"))

      if(b) {
        this.process_all_for_action(entries_delete.rows, "delete");
        this.process_all_for_action(entries_modify.rows, "modify");
      }
    },

    /**
     * Returns object literal with rows and ixf_ids for
     * specified action
     * @method all_entries_for_action
     * @param {jQuery} proposals
     * @param {String} action add | modify | delete
     */

    all_entries_for_action : function(proposals, action) {
      var rows = proposals.find('.suggestions-'+action+' .row.item')
      rows = rows.not('.hidden')

      var ids = []
      rows.each(function() {
        var row = $(this)
        ids.push(row.data("ixf-id"))
      })
      return {rows: rows, ixf_ids: ids}
    },

    /**
     * Batch apply all proposals for action
     * @method process_all_for_action
     * @param {jQuery} rows
     * @param {String} action add | modify | delete
     */

    process_all_for_action : function(rows, action) {
      var ixf_proposals = this;
      rows.each(function() {
        var row = $(this);
        ixf_proposals[action](row);
      });
    },

    /**
     * Create the proposed netixlan
     * @method add
     * @param {jQuery} row jquery result set for proposal row
     */

    add : function(row) {
      var data=this.collect(row);

      row.find('.loading-shim').show();
      row.find('.errors').hide()
      row.find('.validation-error').removeClass('validation-error')
      row.find('.input-note').detach()

      return PeeringDB.API.request(
        "POST",
        "netixlan",
        0,
        data
      ).done((a) => {
        var netixlan = a.data[0]
        netixlan.ix = { name : data.ix_name, id : data.ix_id }
        if(!netixlan.ipaddr4)
          netixlan.ipaddr4 = ""
        if(!netixlan.ipaddr6)
          netixlan.ipaddr6 = ""
        this.netixlan_mod.listing_add(
          netixlan.id, null, this.netixlan_list, netixlan);
        this.detach_row(row);
      }).fail((response) => {
        this.render_errors(row, response);
      }).always(() => {
        row.find('.loading-shim').hide();
      })
    },

    /**
     * Removes the proposal row
     * @method detach_row
     * @param {jQuery} row
     */

    detach_row : function(row) {

      var par = row.parent()
      var proposals = row.closest(".ixf-proposals");

      row.detach();
      this.require_refresh = true;
      if(!par.find('.row.item').not('.hidden').length) {
        par.prev(".header").detach()
        par.detach()
        this.sync_proposals_state(proposals);
      }
    },

    /**
     * This will update the batch actions buttons to
     * be disabled if no actions are left for them to
     * apply
     *
     * This will also remove the proposals contaienr if
     * no actions are left to apply
     * @method sync_proposals_state
     * @param {jQuery} proposals jquery result for exchange proposals
     */

    sync_proposals_state : function(proposals) {
      var button_add_all = proposals.find('button.add-all')
      var button_resolve_all = proposals.find('button.resolve-all')

      if(!this.all_entries_for_action(proposals, 'delete').rows.length) {
        proposals.find('.suggestions-delete').prev('.header').detach();
      }

      if(!this.all_entries_for_action(proposals, 'add').rows.length) {
        button_add_all.prop('disabled',true);
      }
      if(
        !this.all_entries_for_action(proposals, 'delete').rows.length &&
        !this.all_entries_for_action(proposals, 'modify').rows.length
      ) {
        button_resolve_all.prop('disabled',true);
      }

      // make sure all tooltips are closed

      proposals.find('[data-bs-toggle="tooltip"]').each(function() {
        $(this).tooltip("hide");
      });

      if(button_resolve_all.prop('disabled') && button_add_all.prop('disabled'))
        proposals.detach()
    },

    /**
     * Renders the errors of an API request
     * to the proposal row
     * @method render_errors
     * @param {jQuery} row
     * @param {jQuery XHR Response} response
     */

    render_errors : function(row, response) {
      var element, field, msg;
      var errors = row.find('.errors')
      var info = [response.status + " " + response.statusText]
      if(response.status == 400) {
        info = [gettext("The server rejected your data")];
        for(field in response.responseJSON) {
          msg = response.responseJSON[field]
          if(msg && msg.join)
            msg = msg.join(",")
          element = row.find('[data-field="'+field+'"]')
          $('<div>')
            .addClass("editable input-note always-absolute validation-error")
            .text(msg)
            .insertBefore(element);
          element.addClass('validation-error')
        }
      } else if(response.status == 403) {
        info = [gettext("You do not have permissions to perform this action")]
      }

      if(response.responseJSON && response.responseJSON.non_field_errors) {
        info = [];
        var i;
        for(i in response.responseJSON.non_field_errors)
          info.push(response.responseJSON.non_field_errors[i]);
      }
      errors.empty().text(info.join("\n")).show()
    },

    /**
     * Collect all the netixlan fields / values from
     * a proposal row and return them as an object literal
     * @method collect
     * @param {jQuery} row
     */

    collect : function(row) {
      var proposals = row.closest("[data-ixf-proposals-ix]")
      var ix_id = proposals.data("ixf-proposals-ix")
      var ix_name = proposals.data("ixf-proposals-ix-name")
      var net_id = proposals.data("ixf-proposals-net")

      var data = {ixlan_id:ix_id, net_id:net_id, ix_name:ix_name}
      row.find('[data-field]').each(function() {
        var field = $(this)
        if(field.data("value")) {
          data[field.data("field")] = field.data("value");
        } else if(field.attr("type") == "checkbox") {
          data[field.data("field")] = field.prop("checked");
        } else {
          data[field.data("field")] = field.val()
        }
      });
      return data;
    }
  }
)


PeeringDB.IXFPreview = twentyc.cls.define(
  "IXFPreview",
  {

    /**
     * Handle the IX-F import preview request and rendering
     * to UI modal
     *
     * @class IXFPreview
     * @namespace PeeringDB
     */

    request : function(ixlanId, renderTo) {

      /**
       * request a preview for the ixlan with ixlanId
       *
       * @method request
       * @param {Number} ixlanId
       * @param {jQuery} renderTo - render to this element (needs to have
       *    the appropriate children elements to work, they are not
       *    created automatically)
       */

      renderTo.find("#tab-ixf-changes").tab("show");
      renderTo.find('.ixf-result').empty().
        append($("<div>").addClass("center").text("... loading ..."));
      renderTo.find('.ixf-error-counter').empty();
      $.get('/import/ixlan/'+ixlanId+'/ixf/preview', function(result) {
        this.render(result, renderTo);
      }.bind(this)).fail(function(result) {
        if(result.responseJSON) {
          this.render(result.responseJSON, renderTo);
        } else {
          this.render({"non_field_errors": ["HTTP error "+result.status]});
        }
      }.bind(this));
    },

    render : function(result, renderTo) {

      /**
       * Render preview result and errors
       *
       * @method render
       * @param {Object} result - result as returned from the preview request
       * @param {jQuery} renderTo
       *
       *    Needs to have child divs with the following classes
       *
       *
       *    .ixf-errors-list: errors will be rendered to here
       *    .ixf-result: changes will be rendered to here
       *    .ixf-error-counter: will be updated with number of errors
       *
       */

      renderTo.find('.ixf-errors-list').empty()
      renderTo.find('.ixf-result').empty()

      var errors = (result.errors || []).concat(result.non_field_errors || []);

      this.render_errors(errors, renderTo.find('.ixf-errors-list'));
      this.render_data(result.data || [], renderTo.find('.ixf-result'));

      if(!result.data || !result.data.length) {
        if(errors && errors.length) {
          renderTo.find("#tab-ixf-errors").tab("show");
        }
      }
    },

    render_errors : function(errors, renderTo) {
      /**
       * Render the errors, called automatically by `render`
       *
       * @method render_errors
       * @param {Array} errors
       * @param {jQuery} renderTo
       */

      var error, i;

      if(!errors.length)
        return;

      $('.ixf-error-counter').text("("+errors.length+")");

      for(i = 0; i < errors.length; i++) {
        error = errors[i];
        renderTo.append($('<div>').addClass("ixf-error").text(error));
      }
    },

    render_data : function(data, renderTo) {
      /**
       * Renders the changes made by the IX-F import, called automatically
       * by `render`
       *
       * @method render_data
       * @param {Array} data
       * @param {jQuery} renderTo
       */

      var row, i;
      for(i = 0; i < data.length; i++) {
        row = data[i];
        renderTo.append(
          $('<div>').addClass("row ixf-row ixf-"+row.action).append(
            $('<div>').addClass("col-sm-1").text(row.action),
            $('<div>').addClass("col-sm-2").text("AS"+row.peer.asn),
            $('<div>').addClass("col-sm-3").text(row.peer.ipaddr4 || "-"),
            $('<div>').addClass("col-sm-3").text(row.peer.ipaddr6 || "-"),
            $('<div>').addClass("col-sm-1").text(PeeringDB.pretty_speed(row.peer.speed)),
            $('<div>').addClass("col-sm-2").text(row.peer.is_rs_peer?"yes":"no"),
            $('<div>').addClass("col-sm-12 ixf-reason").text(row.reason)
          )
        );
      }
    }
  }
);

PeeringDB.IXFNetPreview =  twentyc.cls.extend(
  "IXFNetPreview",
  {
    /**
     * Handle the IX-F import preview for networks request and rendering
     * to UI modal
     *
     * @class IXFNetPreview
     * @namespace PeeringDB
     */

    request : function(netId, renderTo) {

      /**
       * request a preview for the ixlan with ixlanId
       *
       * @method request
       * @param {Number} netId
       * @param {jQuery} renderTo - render to this element (needs to have
       *    the appropriate children elements to work, they are not
       *    created automatically)
       */

      renderTo.find("#tab-ixf-changes").tab("show");
      renderTo.find('.ixf-result').empty().
        append($("<div>").addClass("center").text("... loading ..."));
      renderTo.find('.ixf-error-counter').empty();
      $.get('/import/net/'+netId+'/ixf/preview', function(result) {
        this.render(result, renderTo);
      }.bind(this)).fail(function(result) {
        if(result.responseJSON) {
          this.render(result.responseJSON, renderTo);
        } else {
          this.render({"non_field_errors": ["HTTP error "+result.status]});
        }
      }.bind(this));
    },

    render_data : function(data, renderTo) {
      /**
       * Renders the changes made by the IX-F import, called automatically
       * by `render`
       *
       * @method render_data
       * @param {Array} data
       * @param {jQuery} renderTo
       */

      var row, i;
      for(i = 0; i < data.length; i++) {
        row = data[i];
        renderTo.append(
          $('<div>').addClass("row ixf-row ixf-"+row.action).append(
            $('<div>').addClass("col-sm-1").text(row.action),
            $('<div>').addClass("col-sm-3").append(
              $('<a>').attr("href", "/ix/"+row.peer.ix_id).text(row.peer.ix_name)
            ),
            $('<div>').addClass("col-sm-2").text(row.peer.ipaddr4 || "-"),
            $('<div>').addClass("col-sm-3").text(row.peer.ipaddr6 || "-"),
            $('<div>').addClass("col-sm-1").text(PeeringDB.pretty_speed(row.peer.speed)),
            $('<div>').addClass("col-sm-2").text(row.peer.is_rs_peer?"yes":"no"),
            $('<div>').addClass("col-sm-12 ixf-reason").text(row.reason)
          )
        );
      }
    }

  },
  PeeringDB.IXFPreview
)

PeeringDB.IXFNetPostmortem =  twentyc.cls.extend(
  "IXFNetPostmortem",
  {
    /**
     * Handle the IX-F import preview for networks request and rendering
     * to UI modal
     *
     * @class IXFNetPostmortem
     * @namespace PeeringDB
     */

    request : function(netId, renderTo) {

      /**
       * request a preview for the ixlan with ixlanId
       *
       * @method request
       * @param {Number} netId
       * @param {jQuery} renderTo - render to this element (needs to have
       *    the appropriate children elements to work, they are not
       *    created automatically)
       */

      renderTo.find("#tab-ixf-changes").tab("show");
      renderTo.find('.ixf-result').empty().
        append($("<div>").addClass("center").text("... loading ..."));
      renderTo.find('.ixf-error-counter').empty();

      var limit = $('#ixf-postmortem-limit').val()
      var btnRefresh = $('#ixf-postmortem-refresh')

      btnRefresh.off("click").click(function() {
        this.request(netId, renderTo);
      }.bind(this));

      $.get('/import/net/'+netId+'/ixf/postmortem?limit='+limit, function(result) {
        this.render(result, renderTo);
      }.bind(this)).fail(function(result) {
        if(result.responseJSON) {
          this.render(result.responseJSON, renderTo);
        } else {
          this.render({"non_field_errors": ["HTTP error "+result.status]});
        }
      }.bind(this));
    },

    render_data : function(data, renderTo) {
      /**
       * Renders the changes made by the IX-F import, called automatically
       * by `render`
       *
       * @method render_data
       * @param {Array} data
       * @param {jQuery} renderTo
       */

      var row, i;
      for(i = 0; i < data.length; i++) {
        row = data[i];
        renderTo.append(
          $('<div>').addClass("row ixf-row ixf-"+row.action).append(
            $('<div>').addClass("col-sm-1").text(row.action),
            $('<div>').addClass("col-sm-3").append(
              $('<a>').attr("href", "/ix/"+row.ix_id).text(row.ix_name)
            ),
            $('<div>').addClass("col-sm-2").text(row.ipaddr4 || "-"),
            $('<div>').addClass("col-sm-3").text(row.ipaddr6 || "-"),
            $('<div>').addClass("col-sm-1").text(PeeringDB.pretty_speed(row.speed)),
            $('<div>').addClass("col-sm-2").text(row.is_rs_peer?"yes":"no"),
            $('<div>').addClass("col-sm-12 ixf-reason").text(row.created + " - " +row.reason)
          )
        );
      }
    }

  },
  PeeringDB.IXFPreview
)


PeeringDB.InlineSearch = {

  init_search : function() {
    if(this.initialized)
      return

    this.keystrokeTimeout = new twentyc.util.SmartTimeout(
      () => {}, 500

    );

    $('#search').keypress(function(e) {
      if(e.which == 13) {
        PeeringDB.InlineSearch.keystrokeTimeout.cancel();
        let quick_search_path = $("#quick-search").attr("action")

        let searchValue = $(this).val();

        // Construct a new URL object
        let url = new URL(window.document.location.origin + quick_search_path);

        // Set or update the 'q' search parameter
        url.searchParams.set('q', searchValue);

        // Navigate to the new URL
        window.document.location.href = url.toString();

        e.preventDefault();
      }
    });

    $('#search').keyup(function(e) {
      if(e.which == 13)
        return;

      PeeringDB.InlineSearch.keystrokeTimeout.set(
        () => {
          PeeringDB.InlineSearch.search($(this).val());
        },
        500
      );

    });

    this.searchResult = $('#search-result');
    this.searchContainer = $('#inline-search-container');
    this.contentContainer = $('#content');

    this.initialized = true;
  },

  search : function(value) {

    if(!value || value.length < 3) {
      if(this.searchContainer.is(":visible")) {
        this.searchContainer.hide();
        this.contentContainer.show();
      }
      return;
    }

    if(this.busy) {
      this.queuedSearch = value;
      return;
    }

    this.busy = true;
    $.get(
      "/api_search",
      { q : value },
      function(data) {
        var val;

        if(typeof data == 'string')
          data = JSON.parse(data)


        twentyc.data.load("sponsors", {callback:function() {
          PeeringDB.InlineSearch.apply_result(data)
          PeeringDB.InlineSearch.busy = false
          if(val=PeeringDB.InlineSearch.queuedSearch) {
            PeeringDB.InlineSearch.queuedSearch = null;
            PeeringDB.InlineSearch.search(val);
          }
        }.bind(this)});
      }
    )

  },

  apply_result : function(data) {
    var i, row, rowNode, type;
    var count = 0;

    var campusIconPath = $("#search-result").data("campus-icon-path");

    for(type in data) {
      if(!this.resultNodes)
        this.resultNodes = {};
      if(!this.resultNodes[type]) {
        this.resultNodes[type] = {
          rl : $("#search-result-length-"+type),
          lst : $("#search-result-"+type)
        }
      }

      this.resultNodes[type].rl.html(data[type].length);
      this.resultNodes[type].lst.empty()
      for(i in data[type]) {
        count++;
        row = data[type][i];
        rowNode = $(document.createElement("div"))
        rowNode.addClass("result_row")
        rowNode.append($('<a>').attr("href", "/"+type+"/"+row.id).text(row.name));

        // add campus icon if applicable

        if(row.campus) {
          rowNode.append(
            $('<span class="icon muted">').append(
              $('<a>').attr("href", "/campus/"+row.campus).append(
                $('<img alt="Part of a campus">').attr("src", campusIconPath)
              )
            )
          );
        }

        var sponsor = (twentyc.data.get("sponsors")[row.org_id] || {});
        if(sponsor && sponsor.name) {
          rowNode.append($('<a>').
            attr("href", "/sponsors").
            addClass("sponsor "+sponsor.css).
            text(sponsor.name+" "+gettext("sponsor")));
        }

        this.resultNodes[type].lst.append(rowNode)


      }
    }

    if(!this.searchContainer.is(":visible") && $('#search').val().length > 2) {
      this.searchContainer.show();
      this.contentContainer.hide();
    }

  }

}

/**
 * api request
 */

PeeringDB.API = {
  request : function(method, ref, id, data, success) {

    var url = "/api/"+ref;
    if(id)
       url += "/"+id

    var prepared;
    if(data) {
      if(method.toLowerCase() == "get")
        prepared = data;
      else
        prepared = JSON.stringify(data);
    }
    return $.ajax(
      {
        url : url,
        method : method,
        contentType : 'application/json',
        data : prepared,
        dataType : 'json',
        success : success
      }
    );

  },
  get : function(ref, id, success) {
    return this.request("GET", ref, id, null, function(r) {
      if(success) {
        success(r.data[0], r);
      }
    });
  },
  list : function(ref, success) {
    return this.request("GET", ref, 0, null, success);
  }
}

/**
 * editable key management endpoint
 */

twentyc.editable.action.register(
  "revoke-org-key",
  {
    execute:  function(trigger, container) {

    }
  }
)

twentyc.editable.module.register(
  "key_perm_listing",
  {
    loading_shim : true,
    PERM_UPDATE : 0x02,
    PERM_CREATE : 0x04,
    PERM_DELETE : 0x08,

    init : function() {
      this.listing_init();
      this.container.on("listing:row-add", function(e, rowId, row, data, me) {
        row.editable("payload", {
          key_prefix : data.key_prefix,
          org_id : data.org_id
        })
      });
    },

    org_id : function() {
      return this.container.data("edit-id");
    },
    key_prefix : function() {
      return this.container.data("edit-key-prefix");
    },
    prepare_data : function(extra) {
      var perms = 0;
      if(this.target.data.perm_u)
        perms |= this.PERM_UPDATE;
      if(this.target.data.perm_c)
        perms |= this.PERM_CREATE;
      if(this.target.data.perm_d)
        perms |= this.PERM_DELETE;
      this.target.data.perms = perms;
      if(extra)
        $.extend(this.target.data, extra);
    },

    add : function(rowId, trigger, container, data) {

      var i, labels = twentyc.data.get("key_permissions");

      for(i=0; i<labels.length; i++) {
        if(labels[i].id == data.entity) {
          data.entity = labels[i].name;
          break;
        }
      }

      data.perm_u = ((data.perms & this.PERM_UPDATE) == this.PERM_UPDATE)
      data.perm_c = ((data.perms & this.PERM_CREATE) == this.PERM_CREATE)
      data.perm_d = ((data.perms & this.PERM_DELETE) == this.PERM_DELETE)

      this.listing_add(rowId, trigger, container, data);
    },

    execute_add : function(trigger, container) {
      this.components.add.editable("export", this.target.data);
      var data = this.target.data;
      this.prepare_data();
      this.target.execute("update", this.components.add, function(response) {
        this.add(data.entity, trigger, container, data);
      }.bind(this));
    },

    execute_remove : function(trigger, container) {
      this.components.add.editable("export", this.target.data);
      var row = this.row(trigger);
      this.prepare_data({perms:0, entity:row.data("edit-id")});
      this.target.execute("remove", trigger, function(response) {
        this.listing_execute_remove(trigger, container);
      }.bind(this));
    },

    submit : function(rowId, data, row, trigger, container) {
      this.target.data = data;
      this.prepare_data({entity:rowId});
      this.target.execute("update", row, function() {
        this.listing_submit(rowId, data, row, trigger, container);
      }.bind(this));
    },

    load : function(keyPrefix) {
      var me = this, target = this.get_target();
      if(!keyPrefix) {
        me.clear();
        return;
      }
      this.container.data("edit-key-prefix", keyPrefix);
      target.data = {"key_prefix":keyPrefix, "org_id":this.org_id()}
      target.execute(null, null, function(data) {
        me.clear();
        var k;
        for(k in data.user_permissions) {
          var perms = {};
          perms.perms = data.user_permissions[k];
          perms.entity = k;
          me.add(k, null, me.container, perms);
        };
      });
    }

  },
  "listing"
);

/**
 * editable uoar management endpoint
 */

twentyc.editable.module.register(
  "uperm_listing",
  {
    loading_shim : true,
    PERM_UPDATE : 0x02,
    PERM_CREATE : 0x04,
    PERM_DELETE : 0x08,

    init : function() {
      this.listing_init();
      this.container.on("listing:row-add", function(e, rowId, row, data, me) {
        row.editable("payload", {
          user_id : data.user_id,
          org_id : data.org_id
        })
      });
    },

    org_id : function() {
      return this.container.data("edit-id");
    },
    user_id : function() {
      return this.container.data("edit-user-id");
    },
    prepare_data : function(extra) {
      var perms = 0;
      if(this.target.data.perm_u)
        perms |= this.PERM_UPDATE;
      if(this.target.data.perm_c)
        perms |= this.PERM_CREATE;
      if(this.target.data.perm_d)
        perms |= this.PERM_DELETE;
      this.target.data.perms = perms;
      if(extra)
        $.extend(this.target.data, extra);
    },

    add : function(rowId, trigger, container, data) {

      var i, labels = twentyc.data.get("permissions");

      for(i=0; i<labels.length; i++) {
        if(labels[i].id == data.entity) {
          data.entity = labels[i].name;
          break;
        }
      }

      data.perm_u = ((data.perms & this.PERM_UPDATE) == this.PERM_UPDATE)
      data.perm_c = ((data.perms & this.PERM_CREATE) == this.PERM_CREATE)
      data.perm_d = ((data.perms & this.PERM_DELETE) == this.PERM_DELETE)

      this.listing_add(rowId, trigger, container, data);
    },

    execute_add : function(trigger, container) {
      this.components.add.editable("export", this.target.data);
      var data = this.target.data;
      this.prepare_data();
      this.target.execute("update", this.components.add, function(response) {
        this.add(data.entity, trigger, container, data);
      }.bind(this));
    },

    execute_remove : function(trigger, container) {
      this.components.add.editable("export", this.target.data);
      var row = this.row(trigger);
      this.prepare_data({perms:0, entity:row.data("edit-id")});
      this.target.execute("remove", trigger, function(response) {
        this.listing_execute_remove(trigger, container);
      }.bind(this));
    },

    submit : function(rowId, data, row, trigger, container) {
      this.target.data = data;
      this.prepare_data({entity:rowId});
      this.target.execute("update", row, function() {
        this.listing_submit(rowId, data, row, trigger, container);
      }.bind(this));
    },

    load : function(userId) {
      var me = this, target = this.get_target();
      if(!userId) {
        me.clear();
        return;
      }
      this.container.data("edit-user-id", userId);
      target.data= {"user_id":userId, "org_id":this.org_id()}
      target.execute(null, null, function(data) {
        me.clear();
        var k;
        for(k in data.key_perms) {
          var perms = {};
          perms.perms = data.key_perms[k];
          perms.entity = k;
          me.add(k, null, me.container, perms);
        };
      });
    }

  },
  "listing"
);


twentyc.editable.module.register(
  "user_listing",
  {
    loading_shim : true,
    org_id : function() {
      return this.container.data("edit-id");
    },

    remove : function(id, row, trigger, container) {
      var b = PeeringDB.confirm(gettext("Remove") + " " +row.data("edit-label"), "remove");  ///
      var me = this;
      $(this.target).on("success", function(ev, data) {
        if(b)
          me.listing_remove(id, row, trigger, container);
      });
      if(b) {
        this.target.data = { user_id : id, org_id : this.org_id() };
        this.target.execute("delete");
      } else {
        $(this.target).trigger("success", [gettext("Canceled")]);  ///
      }
    },
    submit : function(rowId, data, row, trigger, container) {
      this.target.data = data;
      this.target.data.org_id = this.org_id();
      this.target.data.user_id = rowId;
      this.target.execute("update", row, function() {
        this.listing_submit(rowId, data, row, trigger, container);
      }.bind(this));
    },


  },
  "listing"
);

twentyc.editable.module.register(
  "email_listing",
  {
    loading_shim : true,
    org_id : function() {
      return this.container.data("edit-id");
    },

    remove : function(id, row, trigger, container) {
      var b = PeeringDB.confirm(gettext("Remove") + " " +row.data("edit-label"), "remove");  ///
      var me = this;
      $(this.target).on("success", function(ev, data) {
        if(b)
          me.listing_remove(id, row, trigger, container);
      });
      if(b) {
        this.target.data = { email : id };
        this.target.execute("delete");
      } else {
        $(this.target).trigger("success", [gettext("Canceled")]);  ///
      }
    },

    execute_add : function(trigger, container) {
      this.components.add.editable("export", this.target.data);
      this.target.execute("add", this.components.add, function(response) {
        document.location.href = document.location.href;
      }.bind(this));
    },

    execute_primary : function(trigger, container) {
      var row = this.row(trigger);
      var id = row.data("edit-id");
      this.target.data = { email : id };

      $(this.target).on("success", function(ev, data) {
        document.location.href = document.location.href;
      });

      row.editable("export", this.target.data);
        this.target.execute("primary", trigger, function(response) {
      }.bind(this));
    },

    execute_update : function(trigger, container) {
      var row = this.row(trigger);
      row.editable("export", this.target.data);
      this.target.execute("update", trigger, function(response) {
      }.bind(this));
    }

  },
  "listing"
);



twentyc.editable.module.register(
  "key_listing",
  {
    loading_shim : true,
    org_id : function() {
      return this.container.data("edit-id");
    },

    api_key_popin : function(key) {
      const message = gettext("Your API key was successfully created. "
                  + "Write this key down some place safe. "
                  + "Keys cannot be recovered once  "
                  + "this message is exited or overwritten.");

      var panel = $('<div>').addClass("alert alert-success marg-top-15").
        append($('<div>').text(message)).
        append($('<div>').addClass("center marg-top-15").text(key))

      this.container.find("#api-key-popin-frame").empty().append(panel)
    },

    remove : function(id, row, trigger, container) {
      var b = PeeringDB.confirm(gettext("Remove") + " " +row.data("edit-label"), "remove");  ///
      var me = this;
      $(this.target).on("success", function(ev, data) {
        if(b)
          me.listing_remove(id, row, trigger, container);
      });
      if(b) {
        this.target.data = { prefix : id, org_id : this.org_id() };
        this.target.execute("delete");
      } else {
        $(this.target).trigger("success", [gettext("Canceled")]);  ///
      }
    },

    execute_add : function(trigger, container) {
      this.components.add.editable("export", this.target.data);
      var data = this.target.data;
      this.target.execute("add", this.components.add, function(response) {
        if(response.readonly)
          response.name = response.name + " (read-only)";
        this.add(data.entity, trigger, container, response);
        this.api_key_popin(response.key)
      }.bind(this));
    },

    add : function(rowId, trigger, container, data) {
      var row = this.listing_add(data.prefix, trigger, container, data);
      row.attr("data-edit-label", data.prefix + " - " + data.name)
      row.data("edit-label", data.prefix + " - " + data.name)
      var update_key_form = row.find(".update-key")
      update_key_form.find(".popin, .loading-shim").detach()
      update_key_form.editable()
      return row
    },

    execute_update : function(trigger, container) {
      var row = this.row(trigger);
      row.editable("export", this.target.data);
      this.target.execute("update", trigger, function(response) {
      }.bind(this));
    },

    execute_revoke : function(trigger, container) {

      var row = this.row(trigger);
      var b = PeeringDB.confirm(gettext("Revoke key") + " " +row.data("edit-label"), "remove");

      if(!b) {
        container.editable("loading-shim", "hide")
        return
      }

      this.components.add.editable("export", this.target.data);
      var data = this.target.data;
      var id = data.prefix = row.data("edit-id")
      this.target.execute("revoke", trigger, function(response) {
        this.listing_remove(id, row, trigger, container);
      }.bind(this));
    }

  },
  "listing"
);



twentyc.editable.module.register(
  "security_key_listing",
  {
    loading_shim : true,

    remove : function(id, row, trigger, container) {
      var b = PeeringDB.confirm(gettext("Remove") + " " +row.data("edit-label"), "remove");  ///
      var me = this;
      $(this.target).on("success", function(ev, data) {
        if(b)
          me.listing_remove(id, row, trigger, container);
      });
      if(b) {
        this.target.data = { id : id };
        this.target.execute("delete");
      } else {
        $(this.target).trigger("success", [gettext("Canceled")]);  ///
      }
    },

    execute_register : function(trigger, container) {
      SecurityKeys.request_registration(
        (credential_json) => {
          this.components.add.editable("export", this.target.data);
          this.target.data.credential = credential_json;
          var data = this.target.data;
          this.target.execute("add", this.components.add, (response) => {
            this.add(data.entity, trigger, container, response);

            // refresh to pick up django-two-factor page changes
            // from new registration
            document.location.href = document.location.href;

          });
        },
        (exc) => {
          $("#errors-alert").html(`<div class="alert alert-danger">${exc.message}</div>`)
          container.editable("loading-shim", "hide");
          console.error(exc);
        }

      );
    },

    register : function(rowId, trigger, container, data) {
    },

    add : function(rowId, trigger, container, data) {
      var row = this.listing_add(data.prefix, trigger, container, data);
      row.attr("data-edit-label", data.name)
      row.data("edit-label", data.name)
      var update_key_form = row.find(".update-key")
      update_key_form.find(".popin, .loading-shim").detach()
      update_key_form.editable()
      return row
    },

    execute_update : function(trigger, container) {
      var row = this.row(trigger);
      row.editable("export", this.target.data);
      this.target.execute("update", trigger, function(response) {
      }.bind(this));
    },

    execute_remove : function(trigger, container) {
      var row = this.row(trigger);
      var b = PeeringDB.confirm(gettext("Revoke key") + " " +row.data("edit-label"), "remove");

      if(!b) {
        container.editable("loading-shim", "hide")
        return
      }
      this.components.add.editable("export", this.target.data);
      var data = this.target.data;
      var id = data.id = row.data("edit-id")
      this.target.execute("remove", trigger, function(response) {
        this.listing_remove(id, row, trigger, container);

        // refresh to pick up django-two-factor page changes
        // from removal
        document.location.href = document.location.href;


      }.bind(this));
    }

  },
  "listing"
);

twentyc.editable.module.register(
  "passkey_listing",
  {
    loading_shim : true,

    remove : function(id, row, trigger, container) {
      var b = PeeringDB.confirm(gettext("Remove") + " " +row.data("edit-label"), "remove");  ///
      var me = this;
      $(this.target).on("success", function(ev, data) {
        if(b)
          me.listing_remove(id, row, trigger, container);
      });
      if(b) {
        this.target.data = { id : id };
        this.target.execute("delete");
      } else {
        $(this.target).trigger("success", [gettext("Canceled")]);  ///
      }
    },

    execute_register : function(trigger, container) {
      SecurityKeys.request_registration(
        (credential_json) => {
          this.components.add.editable("export", this.target.data);
          this.target.data.credential = credential_json;
          var data = this.target.data;
          data.passkey_login = true
          this.target.execute("add", this.components.add, (response) => {
            this.add(data.entity, trigger, container, response);
            document.location.href = document.location.href;

          });
        },
        (exc) => {
          $("#errors-alert").html(`<div class="alert alert-danger">${exc.message}</div>`)
          container.editable("loading-shim", "hide");
          console.error(exc);
        }

      );
    },

    register : function(rowId, trigger, container, data) {
    },

    add : function(rowId, trigger, container, data) {
      var row = this.listing_add(data.prefix, trigger, container, data);
      row.attr("data-edit-label", data.name)
      row.data("edit-label", data.name)
      var update_key_form = row.find(".update-key")
      update_key_form.find(".popin, .loading-shim").detach()
      update_key_form.editable()
      return row
    },

    execute_update : function(trigger, container) {
      var row = this.row(trigger);
      row.editable("export", this.target.data);
      this.target.execute("update", trigger, function(response) {
      }.bind(this));
    },

    execute_remove : function(trigger, container) {
      var row = this.row(trigger);
      var b = PeeringDB.confirm(gettext("Revoke key") + " " +row.data("edit-label"), "remove");

      if(!b) {
        container.editable("loading-shim", "hide")
        return
      }
      this.components.add.editable("export", this.target.data);
      var data = this.target.data;
      var id = data.id = row.data("edit-id")
      this.target.execute("remove", trigger, function(response) {
        this.listing_remove(id, row, trigger, container);

        // refresh to pick up django-two-factor page changes
        // from removal
        document.location.href = document.location.href;


      }.bind(this));
    }

  },
  "listing"
);



twentyc.editable.module.register(
  "uoar_listing",
  {
    execute_approve : function(trigger, container) {
      var row = trigger.closest("[data-edit-id]").first()

      var b = PeeringDB.confirm(gettext("Add user") + " " +row.data("edit-label")+ " " + gettext("to Organization?"), "approve"); ///
      if(!b)
        return;

      this.target.data = {id:row.data("edit-id")};

      container.editable("export", this.target.data);
      this.target.execute("approve", row, function(data) {
        row.detach()
        var user_listing = $('#org-user-manager').data("edit-module-instance")
        row.data("edit-label", data.full_name)
        user_listing.add(data.id, row, user_listing.container, data)
      });
    },
    execute_deny : function(trigger, container) {
      var row = trigger.closest("[data-edit-id]").first()

      var b = PeeringDB.confirm(gettext("Deny") +" "+row.data("edit-label")+"'s " + gettext("request to join the Organization?"), "deny");  ///
      if(!b)
        return;

      this.target.data = {id:row.data("edit-id")};
      container.editable("export", this.target.data);
      this.target.execute("deny", row, function(data) {
        row.detach();
      });
    }
  },
  "base"
);

/**
 * editable advanced_search endpoint
 */

twentyc.editable.target.register(
  "advanced_search",
  {

    /*
     * called when the `Search` button is clicked
     * needs to prepare url parameters from form data
     */

    execute : function() {

      var i, data = this.data_clean(true);
      data.reftag = this.args[1]

      for(i in data) {
        if(data[i] && data[i].join)
          data[i] = data[i].join(",")
      }


      // handle org autocomplete fields that have `allow-nonexistent` enabled
      // as they could either procude an integer value (id) or a string value
      // (partial name)

      if(data.org) {
        var id = parseInt(data.org);
        if(isNaN(id)) {
          data.org__name__contains = data.org;
          delete data.org;
        }
      } else if(data.org__name__contains) {
        var id = parseInt(data.org__name__contains);
        if(!isNaN(id)) {
          data.org = data.org__name__contains;
          delete data.org__name__contains;
        }
      }


      if(data.reftag == "ix") {
        // we want the unit formatted values in the url paramters
        // so that the unit selection gets persisted in the url
        let capacity = $('[data-edit-name="capacity__gte"]').data("edit-input-instance");
        if(data["capacity__gte"])
          data["capacity__gte"] = capacity.formatted()
      }


      if(parseInt(data.distance) > 0) {
        if(data.country__in && data.country__in.split(",").length > 1) {
          return $(this).trigger("error", {"type": "ValidationError", "field": "country__in", "info": "Please only select one country when filtering by distance."});
        }
        data.country = data.country__in;
        delete data.country__in;
        data.distance = this.sender.find('[data-edit-name="distance"]').data("edit-input-instance").formatted();
      } else if(typeof(data.distance) != "undefined"){
        delete data.distance;
      }

      if(data["undefined"])
        delete data["undefined"]
      window.location.replace(
        '?'+$.param(data)
      );
    },

    /*
     * Handles the search request to the API
     */

    search : function() {
      var reftag = this.args[1];
      var data = this.data_clean(true);
      var me = $(this), mod=this, sender = this.sender, i;
      var campusIconPath = $(".advanced-search-view").data("campus-icon-path");

      for(i in data) {
        if(typeof data[i] == "object" && data[i].join) {
          data[i] = data[i].join(",")
        }
      }

      if(parseInt(data.distance) > 0) {
        data.country = data.country__in;
        delete data.country__in;
      } else if(typeof(data.distance) != "undefined"){
        delete data.distance;
      }


      data.limit = this.limit || 250;
      data.depth = 1;

      //console.log("Advanced Search", data);

      sender.find('.results-empty').hide();
      sender.find('.results-cutoff').hide();

      PeeringDB.advanced_search_result[reftag] = {"param": $.param(data), data : []}

      PeeringDB.API.request(
        "GET",
        reftag,
        null,
        data,
        function(r) {

          me.trigger("success", r.data);

          var resultNode = sender.find('.results').first()
          resultNode.empty();

          if(!r.data.length) {
            sender.find('.results-empty').show();
          } else {
            if(r.data.length == data.limit) {
              sender.find('.results-cutoff').show();
            }
            var row, i, d;
            for(i in r.data) {
              d = r.data[i];

              if(typeof mod["finalize_data_"+reftag] == "function") {
                mod["finalize_data_"+reftag](d);
              }

              row = twentyc.editable.templates.copy("advanced-search-"+reftag+"-item")

              if(d.campus && d.campus.campus_id) {
                $('<a>').
                  attr("href", "/campus/"+d.campus.campus_id).
                  append($('<span class="icon muted">').append($('<img alt="Part of a campus">').attr("src", campusIconPath))).
                  insertAfter(row.find('.name'));
              }

              if(d.sponsorship && d.sponsorship.name) {
                $('<a>').
                  attr("href", "/sponsors").
                  addClass("sponsor "+d.sponsorship.css).
                  text(d.sponsorship.name.toLowerCase()+" "+gettext("sponsor")).
                  insertAfter(row.find('.name'));
              }

              row.find("[data-edit-name]").each(function(idx) {
                var fld = $(this);
                var value = d[fld.data("edit-name")]
                var sortValue = value;

                // if field has a sort-target specified get value for sorting
                // from there instead
                if(fld.data("sort-target")) {
                  sortValue = d[fld.data("sort-target")];
                }
                fld.data("sort-value", typeof sortValue == "string" ? sortValue.toLowerCase() : sortValue);
                fld.html(value);
                if(this.tagName == "A") {
                  fld.attr("href", fld.attr("href").replace("$id", d.id));
                }
              });
              resultNode.append(row);
            }
            sender.sortable("sortInitial");
          }
          PeeringDB.advanced_search_result[reftag].data = r.data
        }
      ).fail(function(response) {
        twentyc.editable.target.error_handlers.http_json(response, me, sender);
      });

    },

    finalize_data_net : function(data) {
      data.ix_count = data.netixlan_set.length;
      data.fac_count = data.netfac_set.length;
      data.info_traffic_raw = twentyc.data.get("traffic_speed_by_label")[data.info_traffic] || 0;
      data.sponsorship = (twentyc.data.get("sponsors")[data.org_id] || {});
    },

    finalize_data_ix : function(data) {
      data.sponsorship = (twentyc.data.get("sponsors")[data.org_id] || {});
    },

    finalize_data_fac : function(data) {
      data.sponsorship = (twentyc.data.get("sponsors")[data.org_id] || {});
      data.campus = (twentyc.data.get("campus_facilities")[data.id] || {});
    },
    finalize_data_carrier : function(data) {
      data.sponsorship = (twentyc.data.get("sponsors")[data.org_id] || {});
      data.facilities = data.carrierfac_set.length;
    }
  },
  "base"
);

/**
 * editable api endpoint
 */

function getExcMessage(response) {
  if (response.responseJSON) {
    const meta = response.responseJSON.meta;
    const message = response.responseJSON.message;

    if (meta && meta.error) {
      return `${meta.error}<br />${message || ''}`;
    }
  }
  return `${response.status} ${response.statusText}`;
}

twentyc.editable.target.register(
  "api",
  {
    execute : function() {
      var endpoint = this.args[1]
      var requestType = this.args[2]
      var operation = this.args[3]
      var method = "POST"

      var button = $(this.sender.context);

      if(this.context) {
        var sender = this.context;
      } else {
        var sender = this.sender;
      }

      var me = $(this),
          data = this.data,
          id = parseInt(this.data._id);
      var social_media = [];
      var social_media_labels = [];
      $("div.view_row.social_media").each(function(idx, val) {
        var identifier = $(val).find("input").val(); // Get the identifier value

        // Check if an identifier exists before pushing the data
        if (identifier) {
          social_media.push({
            "service": $(val).find("select").val(),
            "identifier": identifier
          });
          social_media_labels.push($(val).find("select option:selected").text());
        }
      });

      data.social_media = social_media;
      if(requestType == "update") {
        if(id)
          method = "PUT"
      } else if(requestType == "delete") {
        method = "DELETE"
      } else if(requestType == "create") {
        method = "POST"
      } else {
        throw(gettext("Unknown request type:") + " "+requestType); ///
      }

      if (operation) {
        endpoint += `/${id}/${operation}`;
        id = null;
        method = "POST"
      }

      if(button.data("confirm")) {
        if(!PeeringDB.confirm(button.data("confirm"))) {
          this.sender.editable("loading-shim", "hide")
          return;
        }
      }
      PeeringDB.API.request(
        method,
        endpoint,
        id,
        data,
        function(r) {

          sender.find("div.view_row.social_media").each(function(idx, val) {
            child = $(val).children()
            label = child[0]
            edit_label = child[1]
            $(label).text(social_media_labels[idx])
            $(edit_label).attr('data-edit-value',social_media[idx].service)
            $(edit_label).find("select").each((idxs, el) =>{
              $(el).find('option').each((i, e)=>{
                if($(e).val() == social_media[idx].service){
                  $(e).attr("selected","selected");
                }
              })
              $(el).val(social_media[idx].service).trigger('change')
            })

          });

          if(r)
            me.trigger("success", r.data[0]);
          else
            me.trigger("success", {});
        }
      ).done(function(r) {
        if (r && r.meta && r.meta.geovalidation_warning){
          PeeringDB.add_geo_warning(r.meta, endpoint);
        } else if (r && r.meta && r.meta.suggested_address){
          PeeringDB.add_suggested_address(r, endpoint);
        }

      }).fail(function(r) {
        if(r.status == 400) {
          var k,i,info=[gettext("The server rejected your data")]; ///
          errorType = "HTTPError"
          ignore_field_error = r?.responseJSON?.meta?.ignore_field_error
          ignore_field_error = [true,"True","true"].includes(ignore_field_error)
          if (ignore_field_error){
            errorType = "IgnoreError"
            var k,i,info=[]; ///
          }
          for(k in r.responseJSON) {
            if(k == "meta" && !ignore_field_error) {
              var err = r.responseJSON.meta.error;
              if(err.indexOf(gettext("not yet been approved")) > 0) { //////
                info.push(gettext("Parent entity pending review - please wait for it to be approved before adding entities to it")) ///
              } else if(err != "Unknown")
                info.push(r.responseJSON.meta.error)
              continue;
            }
            sender.find('[data-edit-name="'+k+'"]').each(function(idx) {

              var input = $(this).data("edit-input-instance");
              if(input)
                input.show_validation_error(r.responseJSON[k]);
            });
            if(k == "non_field_errors") {
              var i;
              for(i in r.responseJSON[k])
                info.push(r.responseJSON[k][i].replaceAll("\n","<br />"));
            }
          }

          me.trigger("error", {
            type : errorType,
            info : info.join("<br />")
          });
        } else if (r.status == 403) {
          info = getExcMessage(r);

          me.trigger("error", {
              type: "Http403",
              info: info
          });
        } else if (r.status == 503) {
          info = getExcMessage(r);

          me.trigger("error", {
              type: "Http503",
              info: info
          });
        } else {
            info = getExcMessage(r)

            me.trigger("error", {
                type: "HTTPError",
                info: info
            });
        }
      });
    }
  },
  "base"
);


/*
 * editable api listing module
 */

twentyc.editable.module.register(
  "api_listing",
  {
    loading_shim : true,

    init : function() {
      this.listing_init();

      this.container.on("listing:row-add", function(e, rowId, row, data, me) {
        var target = me.target;
        if(!target)
          target = me.get_target();
        var finalizer = "finalize_row_"+target.args[1];
        if(me[finalizer]) {
          me[finalizer](rowId, row, data);
        }

        // set sorting and filtering values on new row
        row.find('[data-sort-name], [data-filter-name]').each(function(idx) {
          var filter = $(this).data('filter-name')
          var sort = $(this).data('sort-name')
          if(filter)
            $(this).attr('data-filter-value', data[filter])
          if(sort)
            $(this).attr('data-sort-value', data[sort])
        });

        $(this).find("[data-filter-target]").filterInput("retest");
        // always show newly added row
        row.show();
        row.addClass("status-"+data.status)
        PeeringDB.fix_list_offsets()
        if(me.components.add)
            me.components.add.editable("reset");
      });
    },

    add : function(id, trigger, container, data, context) {
      var me =this;
      var sentData = data;
      this.target.data = data;
      this.target.args[2] = "update"
      this.target.context = this.components.add || context;
      $(this.target).on("success", function(ev, data) {
        var finalizer = "finalize_add_"+me.target.args[1];
        if(me[finalizer]) {
          container.editable("loading-shim","show");
          me[finalizer](data, function(data) {
            me.listing_add(data.id, trigger, container, data);
            container.editable("loading-shim","hide");
          }, sentData);
        } else {
          me.listing_add(data.id, trigger, container, data);
        }
      });
      container.editable("clear-error-popins");
      this.target.execute();
    },

    submit : function(id, data, row, trigger, container) {
      data._id = id;
      var me = this;
      this.target.data = data;
      this.target.args[2] = "update"
      this.target.context = row;
      let sub_target = null
      let edit_target = container.data("edit-target");
      const ref_tag = $('[data-ref-tag]').data('ref-tag');
      if(edit_target==="api:netixlan" && ref_tag === "net"){
        sub_target = jQuery.extend(true, {}, this.target);
        const { fac_id, ...rest } = data;
        this.data = rest
        sub_target.data = {
          fac_id
        }
        sub_target.context = row.find("[data-edit-type='autocomplete']").first()
        const sub_edit_target = sub_target.context.data("edit-sub-target")
        sub_target.args = sub_edit_target.split(":")
        sub_target.args[1] = `netixlan/${id}/${sub_target.args[1]}`
        sub_target.args[2] = "create"
      }

      var editForm = $(`[data-edit-target="${edit_target}"]`)

      $(this.target).on("success", function(ev, data) {
        var finalizer = "finalize_update_"+me.target.args[1];
        if(me[finalizer]) {
          me[finalizer](id, row, data);
        }
        if(edit_target==="api:netixlan" && ref_tag === "net"){
          sub_target.execute()
        }
      });
      this.target.execute();
    },

    remove : function(id, row, trigger, container) {
      var b = PeeringDB.confirm(gettext("Remove") + " "+row.data("edit-label"), "remove"); ///
      var me = this;
      $(this.target).on("success", function(ev, data) {
        if(b)
          me.listing_remove(id, row, trigger, container);
      });

      if(b) {
        if(!this.target.args[2])
          this.target.args[2] = "delete";
        this.target.data = { _id : id };
        this.target.execute();
      } else {
        $(this.target).trigger("success", ["Canceled"]);
      }
    },


    execute_add_campus_facility : function(trigger, container) {
      this.components.add.editable("export", this.target.data);
      var data = this.target.data;
      this.target.args[1] = ["campus", data.campus_id, "add-facility", data.fac_id].join("/");
      this.execute_add(trigger, container);
    },

    execute_remove_campus_facility : function(trigger, container) {
      this.components.add.editable("export", this.target.data);
      var data = this.target.data;
      this.target.args[1] = ["campus", data.campus_id, "remove-facility"].join("/");
      this.target.args[2] = "create";
      this.execute_remove(trigger, container);
    },



    // FINALIZERS: IX

    finalize_row_ix : function(rowId, row, data) {
      // finalize ix row after add
      // we need to make sure that the ix name
      // is rendered as a link

      var ixlnk = $('<a></a>');
      if (data.status == "ok") {
        ixlnk.attr("href", "/ix/"+data.id);
      }
      else {
        ixlnk.attr("style", "text-decoration: none;");
      }
      ixlnk.text(data.name);
      row.find(".name").html(ixlnk);

      row.data("edit-label", gettext("Exchange") + ": " +data.name); ///
    },


    // FINALIZERS: NET

    finalize_row_net : function(rowId, row, data) {
      // finalize net row after add
      // we need to make sure that the network name
      // is rendered as a link

      var netlnk = $('<a></a>');
      if (data.status == "ok") {
        netlnk.attr("href", "/net/"+data.id);
      }
      else {
        netlnk.attr("style", "text-decoration: none;");
      }
      netlnk.text(data.name);
      row.find(".name").html(netlnk);

      row.data("edit-label", gettext("Participant") + ": " +data.name); ///
    },


    // FINALIZERS: FAC

    finalize_row_fac : function(rowId, row, data) {
      // finalize fac row after add
      // we need to make sure that the facility name
      // is rendered as a link

      var faclnk = $('<a></a>');

      if (data.status == "ok") {
        faclnk.attr("href", "/fac/"+data.id);
      }
      else {
        faclnk.attr("style", "text-decoration: none;");
      }

      faclnk.text(data.name);
      row.find(".name").html(faclnk);

      row.data("edit-label", gettext("Facility") + ": " +data.name); ///
    },

    // FINALIZERS: CAMPUS

    finalize_row_campus : function(rowId, row, data) {
      // finalize campus row after add
      // we need to make sure that the campus name
      // is rendered as a link

      var faclnk = $('<a></a>');

      faclnk.attr("href", "/campus/"+data.id);
      faclnk.text(data.name);
      row.find(".name").html(faclnk);

      row.data("edit-label", gettext("Campus") + ": " +data.name); ///
    },


    // FINALIZERS: POC

    finalize_row_poc : function(rowId, row, data) {
      row.editable("payload", {
        net_id : data.net_id,
        role : data.role
      })

      //row.find(".phone").val(data.phone);
      var phone = row.find(".phone").data("edit-input-instance")
      phone.set(data.phone)

      row.data("edit-label", gettext("Network Contact") + ": "+data.name);  ///
    },

    finalize_update_poc : function(rowId, row, data) {
      row.find(".phone").text(data.phone);
    },

    // FINALIZERS: NETIX

    finalize_row_netixlan : function(rowId, row, data) {

      // finalize netix row after add
      // we need to make sure that the exchange name
      // is rendered as a link and that speed is
      // formatted in a humanized way

      var ixlnk = $('<a></a>');
      ixlnk.attr("href", "/ix/"+data.ix.id);
      ixlnk.text(data.ix.name);
      row.find(".exchange").html(ixlnk);

      if(data.operational)
        row.addClass("operational")

      //row.find(".asn").html(data.asn)
      row.find(".speed").data("edit-content-backup", PeeringDB.pretty_speed(data.speed))

      row.editable("payload", {
        ixlan_id : data.ixlan.id,
        net_id : data.net.id
      });

      // this needs to be fixed in twentyc.edit.js
      var rs_peer_html = twentyc.editable.templates.copy("check")
      twentyc.editable.input.get("bool").prototype.template_handlers["check"](data.is_rs_peer, rs_peer_html);
      row.find(".is_rs_peer").data("edit-content-backup", rs_peer_html)

      row.data("edit-label", gettext("Network - Exchange link") + ": "+data.ix.name); ///

    },

    finalize_add_netixlan : function(data, callback) {

      // finalize netix data after add
      // we need to get ix name

      if(!data.ipaddr4)
          data.ipaddr4="";
      if(!data.ipaddr6)
          data.ipaddr6="";

      PeeringDB.API.get("ixlan", data.ixlan_id, function(ixlan) {
        data.ixlan = ixlan;
        PeeringDB.API.get("ix", ixlan.ix_id, function(ix) {
          data.ix = ix;
          data.exchange_name = ix.name;
          callback(data);
        });
      });

      // clean up IX-F proposals for ADD suggestions where
      // ipaddresses matches either of the ipaddresses of the newly
      // added netixlan - see #807

      if(data.ipaddr4 != "") {
        let ixf_prop_ip4 = $('.suggestions-add').find('input[value="'+data.ipaddr4+'"]');
        let par = ixf_prop_ip4.parents(".item")
        ixf_prop_ip4.val("")
        if(par.find('input[data-field="ipaddr6"]').val() == "") {
          PeeringDB.ixf_proposals.detach_row(par);
        }
      }

      if(data.ipaddr6 != "") {
        let ixf_prop_ip6 = $('.suggestions-add').find('input[value="'+data.ipaddr6+'"]');
        let par = ixf_prop_ip6.parents(".item")
        ixf_prop_ip6.val("")
        if(par.find('input[data-field="ipaddr4"]').val() == "") {
          PeeringDB.ixf_proposals.detach_row(par);
        }
      }

    },

    finalize_port_location: function(port_location){
      fac_id = port_location.data("edit-value")
      fac_name = port_location.data("edit-autocomplete-text")
      fac_link = `<a href="/fac/${fac_id}">${fac_name}</a>`
      port_location.html(fac_link)
    },
    waitForEdit: function () {
        return new Promise((resolve) => {
          const checkAttribute = setInterval(() => {
              if (!$("#view").hasClass("mode-edit")) {
                  clearInterval(checkAttribute);
                  resolve();
              }
          }, 100);
      });
    },
    finalize_update_netixlan : async function(rowId, row, data) {
      const ref_tag = $('[data-ref-tag]').data('ref-tag');
      if(ref_tag === "ix" || ref_tag === "net"){
        await this.waitForEdit();
        port_location = row.find(`[data-edit-name='fac_id'][data-edit-id='${rowId}']`).first()
        this.finalize_port_location(port_location)
      }
      var pretty_speed = PeeringDB.pretty_speed(data.speed)
      row.find(".speed").data("edit-content-backup", pretty_speed)
      row.find(".speed").data("edit-value", data.speed)
      row.find(".speed").text(pretty_speed)
      if(data.operational)
        row.addClass("operational")
      else
        row.removeClass("operational")
    },


    // FINALIZERS: NETFAC

    finalize_row_netfac : function(rowId, row, data) {

      // finalize netfac row after add
      // we need to make sure that the facility name
      // is rendered as a link

      var faclnk = $('<a></a>');
      faclnk.attr("href", "/fac/"+data.fac_id);
      faclnk.text(data.facility);
      row.find(".facility").html(faclnk);

      row.editable("payload", {
        fac_id : data.fac_id,
        net_id : data.net_id,
        local_asn : data.local_asn
      });

      row.data("edit-label", gettext("Network - Facility link") + ": "+data.facility); ///

    },

    finalize_add_netfac : function(data, callback) {

      // finalize netfac data after add
      // we need to get facility data so we can fill in
      // the fields accordingly

      PeeringDB.API.get("fac", data.fac_id, function(r) {
        data.country = r.country;
        data.city = r.city;
        data.fac_id = r.id;
        data.facility = r.name;
        callback(data);
      });

    },

    // FINALIZERS: IXLAN PREFIX

    finalize_row_ixpfx : function(rowId, row, data) {
      row.editable("payload", {
        ixlan_id : data.ixlan_id
      })
      row.data("edit-label", gettext("IXLAN Prefix") +data.prefix);  ///
    },

    // FINALIZERS: IXFAC

    finalize_row_ixfac : function(rowId, row, data) {

      // finalize icfac row after add
      // we need to make sure that the facility name
      // is rendered as a link

      var faclnk = $('<a></a>');
      faclnk.attr("href", "/fac/"+data.fac_id);
      faclnk.text(data.facility);
      row.find(".facility").html(faclnk);

      row.editable("payload", {
        fac_id : data.fac_id,
        ix_id : data.ix_id,
      });

      row.data("edit-label", gettext("Exchange - Facility link") + ": "+data.facility); ///

    },

    finalize_add_ixfac : function(data, callback) {

      // finalize ixfac data after add
      // we need to get facility data so we can fill in
      // the fields accordingly
      //
      // this is identical to what we need to for netfac, so
      // just use that

      this.finalize_add_netfac(data, callback);

    },

    // FINALIZERS: CARRIER_FACILITY

    finalize_row_carrierfac : function(rowId, row, data) {

      // finalize icfac row after add
      // we need to make sure that the facility name
      // is rendered as a link

      var faclnk = $('<a></a>');
      faclnk.attr("href", "/fac/"+data.fac_id);
      faclnk.text(data.facility);
      row.find(".facility").html(faclnk);

      row.editable("payload", {
        fac_id : data.fac_id,
        ix_id : data.ix_id,
      });

      row.data("edit-label", gettext("Carrier presence at Facility") + ": "+data.facility); ///

      if(data.status == "pending") {
        row.find(".status").text(data.status);
      }

    },

    finalize_add_carrierfac : function(data, callback) {

      // finalize carrierfac data after add
      // we need to get facility data so we can fill in
      // the fields accordingly
      //
      // this is identical to what we need to for netfac, so
      // just use that
      this.finalize_add_netfac(data, callback);


    }

  },
  "listing"
);

/*
 * showdown (markdown) input type
 */

twentyc.editable.input.register(
  "social_media",
  {
    apply : function(value) {
      let service = this.source.parent().find('[data-edit-toggled="view"].view_field').text().trim();
      this.source.html(PeeringDB.social_media_link(value, service.toLowerCase()));
    }
  },
  "string"
)

twentyc.editable.input.register(
  "markdown",
  {

    apply : function(value) {
      var converter = new showdown.Converter()
      if(!value)
        value = "";
      var html = converter.makeHtml(value.replace(/>/g, '&gt;').replace(/</g, '&lt;'))
      this.source.html(DOMPurify.sanitize(html, {SAFE_FOR_JQUERY: true}))
      this.source.find('a').each(function(idx) {
        var url = $(this).attr("href"), valid = true;
        if(url && !url.match(/^([^:]+):/))
          url = "http://"+url;
        if(url && !url.match(/^(http|https):/i))
          valid = false;
        if(!valid || !url)
          $(this).attr("href","")
        else
          $(this).attr("href", url)
      });
      this.source.data("edit-value", value)
    }
  },
  "text"
);

twentyc.editable.input.register(
  "readonly",
  {
    make : function() {
      return $('<span class="editable input-note-relative"></span>')
    },
    set : function(value) {
      this.element.text(value)
    },
    get : function(value) {
      return this.element.text()
    }
  },
  "text"
);

/*
 * mandatory boolean input type
 * renders a drop down with 3 choices
 *
 * - `-`
 * - `yes`
 * - `no`
 *
 * Will raise input-required validation error if `-`
 * is selected upon form submission
 */

twentyc.editable.input.register(
  "mandatory_bool",
  {

    make : function() {
      var node = this.select_make();
      this.source.data("edit-required", "yes")
      return node;
    },

    set : function() {
      this.load();
    },

    load : function() {
      this.select_load([
        {id: "", name: "-"},
        {id: "1", name: gettext("Yes")},
        {id: "0", name: gettext("No")},
      ])
    }
  },
  "select"
);


/*
 * autocomplete input type
 */

twentyc.editable.input.register(
  "autocomplete",
  {
    confirm_handlers : {},

    apply : function(value){
      // change data-edit-autocomplete-text and data-edit-value using javascript built-in functions. because if using jquery does not work
      source = document.querySelector(`[data-edit-id="${this.source.data('edit-id')}"][data-edit-type="autocomplete"]`)
      if (source){
        source.setAttribute("data-edit-autocomplete-text",this.element.val())
        source.setAttribute("data-edit-value",this.get())
      }
      this.source.data("edit-autocomplete-text",this.element.val())
      this.source.data("edit-value",this.get())
    },
    changed : function() {
      return this.original_value !== this.get()
    },
    make : function() {
      let input = this.string_make();
      let multi = this.source.data('edit-multiple')

      if(multi) {
        let choices = $('<div>').addClass('autocomplete-choices')
        input.data('choices_element', choices);
      }

      return input;
    },

    wire : function() {
      var widget = this;
      var input = this.element;

      var multi = this.source.data('edit-multiple')
      var input_min_char = this.source.data("edit-autocomplete-mincharacter")
      if(multi) {
        this.element.data('choices_element').insertAfter(this.element);
      }

      input.yourlabsAutocomplete(
        {
          url : "/autocomplete/"+this.source.data("edit-autocomplete"),
          minimumCharacters : input_min_char ?? 2,
          choiceSelector : "span",
          inputClick : function(e) {
            if (input_min_char !== undefined && input_min_char === 0){
              input.trigger("input")
            }
          }
        }
      ).input.bind("selectChoice", function(a,b) {

        if(multi) {

          // multiple-select support

          widget.multi_add(b.data("value"), b.text());

        } else {

          // single select only

          input.data("value" , b.data("value"));
          input.val(b.text());
          input.removeClass("invalid");
          input.addClass("valid");
          this.render_confirm(b.data("value"));
        }
      }.bind(this));
      // turn off auto-complete firefox workaround
      if(/Firefox/i.test(navigator.userAgent)) {
        $(window).off('scroll', $.proxy(this.hide, this))
      }

      if(this.source.data("edit-autocomplete-text") && this.source.data("edit-value")) {
        input.val(this.source.data("edit-autocomplete-text"));
        input.data("edit-value", this.source.data("edit-value"));
        input.data("value", this.source.data("edit-value"));
        this.original_value = this.source.data("edit-value");
      }


      if(this.source.data("edit-autocomplete-allow-nonexistent")) {
        $(input).on("keyup", function() { input.data("value", $(this).val()); });
      }


    },


    multi_add : function(value, text) {
      // update input value
      let selected = this.element.data("value")
      if(!selected)
        selected = []
      else
        selected = selected.split(",")

      selected.push(value);
      this.element.data("value", selected.join(","));
      this.element.val()

      // update choice display
      let choices_element = this.element.data('choices_element')
      let row = $('<div class="alert autocomplete-choice alert-info">').attr('data-value', value);
      row.attr("data-bs-toggle","tooltip").attr("title", gettext("Click to remove") ).attr("data-placement", "left").tooltip()
      row.on('click',()=> {
        row.tooltip("hide")
        this.multi_remove(value);
      });

      choices_element.append(
        row.text(text)
      );
    },

    multi_remove : function(value) {
      let selected = this.element.data("value")
      let choices_element = this.element.data('choices_element')
      if(!selected)
        return;
      else
        selected = selected.split(",")

      var index = selected.indexOf(""+value);
      if(index > -1)
        selected.splice(index, 1)
      this.element.data("value", selected.join(","));

      choices_element.find(`[data-value="${value}"]`).detach();
    },

    reset_confirm : function() { this.confirm_node().empty(); },
    render_confirm : function(id) {
      var hdl;
      if(hdl=this.confirm_handlers[this.source.data("edit-autocomplete")])
        hdl.apply(this, [id])
    },
    confirm_node : function() {
      return this.source.siblings("[data-autocomplete-confirm]")
    },
    reset : function(resetValue) {
      let multi = this.source.data('edit-multiple')
      if(resetValue) {
        twentyc.editable.input.get("base").prototype.reset.call(this, resetValue);
        this.element.data("value","")
        this.reset_confirm();
        if(multi) {
          this.element.data("choices_element").empty()
        }
      }
    },
    get : function() {
      var val = this.element.data("value");
      if(val === 0 || val === "" || typeof(val) == "undefined") {
        if(this.source.data("edit-autocomplete-allow-nonexistent")) {
          val = this.element.val();
        }
      }
      return val;
    },
    set : function(value) {
      let multi = this.source.data('edit-multiple')

      if(multi && value) {


        let i, item;
        value = value.split(",")
        for(i = 0; i < value.length; i++) {
          item = value[i].split(";")
          this.multi_add(item[0], item[1])
        }

      } else {

      if(value && value.split)
        var t = value.split(";");
      else
        var t = []
      this.element.data("value", t[0]);
      this.element.val(t[1]);
      this.original_value = t[0];
      }
    },
    validate : function() {
      if(!this.source.data("edit-autocomplete-allow-nonexistent")) {
        let multi = this.source.data('edit-multiple')
        let val = this.get()
        if(val) {
          if(multi) {
            let i;
            val = val.split(",")
            for(i = 0; i < val.length; i++) {
              if(!( parseInt(val[i]) >0))
                return false
            }
            return true;
          }
          return this.get() > 0;
        }
      }
      return true;
    }
  },
  "string"
);

twentyc.editable.input.get("autocomplete").prototype.confirm_handlers.fac = function(id) {
  PeeringDB.API.get("fac", id, function(data) {
    this.confirm_node().html(
      [
      $('<div>').text(data.address1),
      $('<div>').text(data.address2),
      $('<div>').text(data.city+", "+data.state+", "+data.zipcode),
      $('<div>').text(data.country)
      ]
    )
  }.bind(this));
}

/*
 * network speed input type
 */



twentyc.editable.input.register(
  "network_speed",
  {
    apply : function(value) {
      this.source.html(PeeringDB.pretty_speed(this.get()));
    },

    export : function() {
      return this.convert(this.get())
    },

    convert : function(value) {
      if ( $.isNumeric(value) ){
        return value
      } else {
      return this.reverse_pretty_speed(value)
      }
    },

    validate : function() {
      // Check if it's an integer
      let value = this.element.val();
      let suffix = value.slice(-1);

      if(this.source.data('edit-required') != "yes" && !value)
        return true;

      if ( $.isNumeric(value) ){
        return true
      } else if ( $.isNumeric(value.slice(0,-1) ) && this.validate_suffix(suffix)) {
        return true
      }
      return false
    },
    validation_message : function() {
      return gettext("Needs to be an integer or a speed ending in M, G, or T") ///
    },

    validate_suffix: function(suffix) {
      return ( suffix.toLowerCase() === "m" ||
               suffix.toLowerCase() === "g" ||
               suffix.toLowerCase() === "t" )
    },

    reverse_pretty_speed : function(value) {
      // Given a pretty speed (string), output the integer speed

      const conversion_factor = {
        "m": 1,
        "g": 1000,
        "t": 1000000,
      }

      const num = parseFloat(value.slice(0, -1));
      const unit = value.slice(-1).toLowerCase();
      const multiplier = conversion_factor[unit]

      // Always return the speed as an integer
      return Math.round(num * multiplier)
  },


  },
  "string"
);

twentyc.editable.input.register(
  "unit_input",
  {

    unit_name : "unit",
    units : [
      {"id": "unit","name": "Unit"}
    ],
    selected_unit : "unit",

    apply : function(value) {
      this.source.text(this.format_units(value));
    },

    set : function(value) {
      let value_to_set = value ? value : this.source.text().trim();
      let m;
      value_to_set = ""+value_to_set;
      if ( m = value_to_set.match(/ ?([a-zA-Z ]+)$/)){
        this.element.val(value_to_set.replace(/[a-zA-Z ]+$/,''));
        this.element.data('unit_select').val(m[1]);
        this.original_unit = m[1];
      } else {
        this.set_value(value_to_set)
      }

      this.element.data('unit_select').insertAfter(this.element);
    },

    set_value : function(value) {
      this.element.val(value);
    },


    get_unit : function() {
      return this.element.data('unit_select').val()
    },

    changed : function() {
      let unit_changed = (this.element.data('unit_select').val() != this.original_unit);
      let value_changed = (this.get() != this.original_value);
      return (value_changed || unit_changed);
    },

    make : function() {
      let input = $('<input class="unit" type="text"></input>')
      let select = $(`<select name="${this.unit_name}" id="${this.unit_name}">`);

      let selected = this.selected_unit;

      $(this.units).each(function(){
        let opt = $('<option>')
        opt.val(this.id).text(this.name)
        if(selected == this.name)
          opt.prop('selected', true);
        select.append(opt);
      });

      input.data('unit_select', select);

      this.original_unit = select.val();


      return input;
    },

    export : function() {
      let unit = this.get_unit();
      let value = this.get();
      if(!value)
        return null;
      return this.convert(value, unit)
    },

    convert : function(value, unit) {
      return value;
    },

    validate : function() {
      // Check if it's an integer
      let value = this.element.val();
      if(!value)
        return true;
      if ( $.isNumeric(value) ){
        return true
      }
      return false
    },

    formatted: function() {
      return this.get()+this.element.data("unit_select").val()
    },


    format_units : function(value) {
      return value;
    },

    reset : function(value) {
      this.string_reset(value);
      this.element.data("unit_select").val(this.selected_unit);
    }

  },
  "string"
);

twentyc.editable.input.register(
  "traffic_capacity",
  {
    unit_name : "traffic_capacity",
    selected_unit : "Gbps",
    units : [
      {
        "name": "Mbps",
        "id": "Mbps"
      },
      {
        "name": "Gbps",
        "id": "Gbps"
      },
      {
        "name": "Tbps",
        "id": "Tbps"
      }
    ],
    convert : function(value, unit) {
      if ( unit == "Mbps"){
        return parseInt(value)
      } else if (unit == "Gbps"){
        return parseInt(value * 1000);
      } else if (unit == "Tbps"){
        return parseInt(value * 1000000);
      }
    },

    set_value : function(value) {

      if(value >= 1000000) {
        value = value / 1000000;
        this.element.data('unit_select').val('Tbps')
      } else if(value >= 1000) {
        value = value / 1000;
        this.element.data('unit_select').val('Gbps')
      } else if(value) {
        this.element.data('unit_select').val('Mbps')
      }

      this.element.val(value);

    },

    format_units: function(value) {
      if(!value)
        return "";

      return value;

    }
  },
  "unit_input"
);

twentyc.editable.input.register(
  "spatial_distance",
  {
    unit_name : "spatial_distance",
    selected_unit : "km",
    units : [
      {
        "name": "km",
        "id": "km"
      },
      {
        "name": "miles",
        "id": "miles"
      }
    ],
    convert : function(value, unit) {
      if ( unit == "km"){
        return parseInt(value)
      } else {
        return parseInt(value / 0.621371);
      }
    },

    format_units: function(value) {
      if(!value)
        return "";

      return value;

    }
  },
  "unit_input"
);

/**
 * a select input that forces to user to change
 * its value if specific conditions are met.
 *
 * @class data_quality_select
 */

twentyc.editable.input.register(
  "data_quality_select",
  {

    /**
     * returns an array of values that are deemed bad
     * and should force the user to make a change
     *
     * this is specified in the data-edit-bad-values
     * html attribute
     *
     * @method bad_values
     * @returns {Array|null}
     */

    bad_values : function() {
      let bad_values = this.source.data("edit-bad-values");
      if(bad_values)
        return bad_values.split(";");
      return null;
    },

    /**
     * Checks if the specified value is a bad value
     * If no value is specified the current element
     * input value is used.
     *
     * @method has_bad_value
     * @param {String} value
     * @returns {Bool}
     */

    has_bad_value : function(value) {

      let bad_values = this.bad_values();

      if(typeof(value) == "undefined") {
        value = this.get();
      }

      if(bad_values) {
        let i, bad_value;
        for(i = 0; i < bad_values.length; i++) {
          bad_value = bad_values[i]
          if(value == bad_value) {
            this.element.addClass("invalid-choice");
            return true;
          }
        }
      }

      this.element.removeClass("invalid-choice");
      return false;
    },

    /**
     * We override the change method to always
     * return true if the current value is a bad value
     *
     * This forces the user to change it before the
     * save can be made.
     */

    changed : function() {
      if(this.has_bad_value())
        return true;
      return this.select_changed()
    },

    /**
     * When adding options to the select element we
     * check each option to see if it contains a bad
     * value and if it does, mark it as such
     */

    finalize_opt : function(opt) {
      if(this.has_bad_value(opt.val())) {
        opt.addClass("invalid-choice");
      }
      return opt;
    },

    /**
     * For inputs that have a good value, we don't want
     * the option for a bad value to still exist in the dropdown
     *
     * We override load to check this and remove the options
     * if necessary.
     *
     * Inputs that have a bad value still need the bad value option
     * available in order to communicate to the user the the value
     * is bad and needs changing
     */

    load : function(data) {
      let k, bad_values = this.source.data("edit-bad-values");
      let value = this.source.data("edit-value")
      if(!this.has_bad_value(value) && bad_values) {
        bad_values = bad_values.split(";")
        let _data = [];
        for(k in data) {
          if($.inArray(data[k].id, bad_values) == -1)
            _data.push(data[k])
        }
        data = _data;
      }


      this.select_load(data);
    },

    /**
     * We wire a change event so that when a bad value is
     * changed to a good value by the user, the error
     * css is removed from the element (done through the
     * has_bad_value() method)
     */

    wire : function() {
      this.has_bad_value();
      this.element.on("change", () => {
        this.has_bad_value(this.element.val());
      })
    }


  },

  "select"
);

/**
 * input element for image file uploads
 */

twentyc.editable.input.register(
  "image",
  {
    make : function() {

      // main node holding all elements making up the upload UX
      var node = $('<div class="file-upload">');

      // element holding current image (if exists)
      let current = $('<div class="current">');

      // element holding upload image input
      let upload = $('<div class="upload">');

      // we need to copy the current image from the view-mode
      // element so we can display it
      let image = this.source.find('img').clone();

      // file selection input
      let input = $('<input type="file" style="display:inline">');

      // loading shim
      let loading = $('<div class="editable loading-shim single-field-shim">').hide();

      // set file type accept
      let accept = this.source.data("edit-accept");

      // file upload button
      var buttonUpload = $('<input type="button" class="btn btn-sm btn-default">').
        val(gettext("Upload")).hide();

      // button to clear image
      var buttonClear = $('<input type="button" class="btn btn-sm btn-danger btn-clear">').
        val(gettext("Remove")).hide();


      // when selecting a file we want to show the upload button
      // and clear any validation errors

      input.on("change", () => {
        this.close_note();
        buttonUpload.show();
      });

      // if current image exists show the "Remove" button

      if(this.source.data("edit-value")) {
        buttonClear.show();
      }

      // clicking the upload button needs to close any validation
      // errors and process the upload

      buttonUpload.click(() => {
        this.close_note();
        this.upload();
      });

      // clicking the remove button needs to close any validation
      // errors and process the file removal

      buttonClear.click(() => {
        this.close_note();
        this.remove_file();
      });

      // assemble the UX nodes

      current.append(image).append(buttonClear);
      upload.append(input).append(buttonUpload);
      node.append(current).append(upload).append(loading);

      if(accept)
        input.attr("accept", accept);

      return node;
    },

    /**
     * sends a DELETE request to data-edit-upload-path
     * and will clear the current image from the UX
     */

    remove_file : function() {
      let name = this.source.data("edit-name");
      this.element.find('.loading-shim').show();
      $.ajax({
        url: this.source.data("edit-upload-path"),
        method: 'delete',
      }).done(() => {
        // success clear current and preview images
        this.source.find('img').hide();
        this.element.find('img').hide();
        // hide the "Remove" button
        this.element.find('.btn-clear').hide();
        this.element.find('.loading-shim').hide();
      }).fail((r) => {
        // failure - show validation error
        this.show_validation_error(PeeringDB.handle_xhr_json_error(r, name))
        this.element.find('.loading-shim').hide();
      });
    },

    /**
     * sends a POST file upload request to data-edit-upload-path
     * and will update the current image in the UX
     */

    upload : function() {
      var data = new FormData();
      let name = this.source.data("edit-name");

      this.element.find('.loading-shim').show();

      // prepare file data
      var file = this.element.find('input[type="file"]')[0].files[0];
      data.append(name, file);

      // upload file data to data-edit-upload-path via POST request
      $.ajax({
        url: this.source.data("edit-upload-path"),
        method: 'post',
        data: data,
        contentType: false,
        processData: false,
      }).done((r) => {
        // success - update current and preview image sources
        // to new url and show the "Remove" button
        this.source.find('img').attr('src', r["url"]).show();
        this.element.find('img').attr('src', r["url"]).show();
        this.element.find('.btn-clear').show();
        this.element.find('.loading-shim').hide();
      }).fail((r) => {

        // failure - show validation error
        if(r.status == 413) {
          let maxSize = this.source.data("edit-max-size");
          if(maxSize) {
            maxSize = ", max. " + parseInt(maxSize / 1024) + "kb";
          } else {
            maxSize = "";
          }
          this.show_validation_error(gettext("File size too big")+maxSize);
        } else {
          this.show_validation_error(PeeringDB.handle_xhr_json_error(r, name));
        }

        this.element.find('.loading-shim').hide();
      });
    },

    /**
     * When resturing UX to view mode we just want to clone
     * the preview image to the field
     */

    apply : function() {
      this.source.empty().append(this.element.find('img').clone());
    }
  },
  "string"
)


/*
 * set up input templates
 */

twentyc.editable.templates.register("check", $('<img class="checkmark" />'));
twentyc.editable.templates.register("poc_email", $('<a></a>'));

/*
 * set up input template handlers
 */

twentyc.editable.input.get("bool").prototype.template_handlers["check"] = function(value, node, input) {
  if(input)
    node.attr("src", STATIC_URL+"checkmark"+(input.get()?"":"-off")+".png");
  else
    node.attr("src", STATIC_URL+"checkmark"+(value?"":"-off")+".png");
}

twentyc.editable.input.get("string").prototype.template_handlers["poc_email"] = function(value, node, input) {
  var email = input.source.next().data("edit-input-instance").get()
  if(email) {
    node.attr("href", "mailto:"+email)
  } else {
    node.addClass("empty")
  }
  node.text(input.get());
}

/*
 *  set up data loaders
 */

twentyc.data.loaders.register(
  "data",
  {
    data : function(id, config) {
      config.url = "/data/"+id;
      this.XHRGet(id, config);
    }
  },
  "XHRGet" ///
);

twentyc.data.loaders.register(
  "org_admin",
  {
    "org_admin" : function(id, config) {
      config.url = "/org_admin/"+id;
      config.data = {org_id:this.orgId};
      this.XHRGet(id, config);
    }
  },
  "XHRGet" ///
);

twentyc.data.loaders.register(
  "network_data",
  {
    "network_data" : function(id, config) {
      config.url = "/data/"+id
      config.data = {id:this.id};
      this.XHRGet(id, config);
    }
  },
  "XHRGet" ///
);

$.urlParam = function(name){
  var results = new RegExp('[?&]' + name + '=([^&#]*)').exec(window.location.href);
  if(!results)
    return 0;
  return results[1] || 0;
}

twentyc.data.loaders.assign("locales", "data");
twentyc.data.loaders.assign("countries", "data");
twentyc.data.loaders.assign("countries_b", "data");
twentyc.data.loaders.assign("facilities", "data");
twentyc.data.loaders.assign("sponsors", "data");
twentyc.data.loaders.assign("campus_facilities", "data");
twentyc.data.loaders.assign("my_organizations", "data");
twentyc.data.loaders.assign("enum/regions", "data");
twentyc.data.loaders.assign("enum/org_groups", "data");
twentyc.data.loaders.assign("enum/media", "data");
twentyc.data.loaders.assign("enum/net_types", "data");
twentyc.data.loaders.assign("enum/net_types_multi_choice", "data");
twentyc.data.loaders.assign("enum/net_types_trunc", "data");
twentyc.data.loaders.assign("enum/net_types_advs", "data");
twentyc.data.loaders.assign("enum/ratios", "data");
twentyc.data.loaders.assign("enum/ratios_trunc", "data");
twentyc.data.loaders.assign("enum/ratios_advs", "data");
twentyc.data.loaders.assign("enum/traffic", "data");
twentyc.data.loaders.assign("enum/scopes", "data");
twentyc.data.loaders.assign("enum/scopes_trunc", "data");
twentyc.data.loaders.assign("enum/scopes_advs", "data");
twentyc.data.loaders.assign("enum/protocols", "data");
twentyc.data.loaders.assign("enum/poc_roles", "data");
twentyc.data.loaders.assign("enum/poc_visibility", "data");
twentyc.data.loaders.assign("enum/policy_general", "data");
twentyc.data.loaders.assign("enum/policy_locations", "data");
twentyc.data.loaders.assign("enum/policy_contracts", "data");
twentyc.data.loaders.assign("enum/visibility", "data");
twentyc.data.loaders.assign("enum/bool_choice_str", "data");
twentyc.data.loaders.assign("enum/bool_choice_with_opt_out_str", "data");
twentyc.data.loaders.assign("enum/service_level_types_trunc", "data");
twentyc.data.loaders.assign("enum/service_level_types_advs", "data");
twentyc.data.loaders.assign("enum/terms_types_trunc", "data");
twentyc.data.loaders.assign("enum/terms_types_advs", "data");
twentyc.data.loaders.assign("enum/property", "data");
twentyc.data.loaders.assign("enum/available_voltage", "data");
twentyc.data.loaders.assign("enum/reauth_periods", "data");
twentyc.data.loaders.assign("enum/mtus", "data");
twentyc.data.loaders.assign("enum/social_media_services", "data");

const checkAsSet = () =>{
  // check the use of hierarchical AS-SET name and if a non-hierarchical AS-SET name is already in use

  const isHierarchicalAsSet = (as_set) => /^[a-zA-Z0-9_-]+(?:::|@)[a-zA-Z0-9_-]+$/.test(as_set.trim());

  const irr_as_set_container = $("div[data-edit-name='irr_as_set']");
  let debounceTimeout;
  const original_as_set = irr_as_set_container.text()
  if (irr_as_set_container.length) {
    irr_as_set_container.on("input focus", "input", (e) => {
      clearTimeout(debounceTimeout);
      debounceTimeout = setTimeout(() => {
        const irr_as_set = e.target.value.trim();
        if(irr_as_set == ""){
          irr_as_set_container.tooltip('dispose');
          return
        }

        if (!isHierarchicalAsSet(irr_as_set)) {
          const has_warning = irr_as_set_container.children().length > 1;
          const url = `/api/net?irr_as_set=${irr_as_set}`;
          const nonhierarchical_as_set_message = gettext("Clearly name your AS-SET with a hierarchical name, e.g. RIPE::AS-RIPENCC")

          if (original_as_set.trim().toLowerCase() !== irr_as_set.toLowerCase() && irr_as_set !== ""){
            // check the non-hierarchical AS-SET is already use or not
            const nonhierarchical_as_set_already_exists_message = gettext(`An AS-SET with this name already exists, avoid ambiguity by specifying the name of the IRR you use e.g. "IRR::AS-MYNAME"`)
            $.ajax({
                url,
                success: (data) => {
                  const existing_data_length = data.data.length;
                  const warning_message = `<small class="text-danger">${nonhierarchical_as_set_already_exists_message}</small>`;
                  if (existing_data_length === 0 && has_warning) {
                    irr_as_set_container.children().last().remove();
                  } else if (existing_data_length !== 0 && !has_warning) {
                    irr_as_set_container.append(warning_message);
                  }
                }
            });
          }
          irr_as_set_container.tooltip({ 'title':  nonhierarchical_as_set_message }).tooltip('show');
        }else{
          irr_as_set_container.tooltip('dispose');
        }
      }, 200);
    });
  }
}

$(twentyc.data).on("load-enum/traffic", function(e, payload) {
  var r = {}, i = 0, data=payload.data;
  for(i=0; i<data.length; i++)
    r[data[i].name] = i
  twentyc.data._data["traffic_speed_by_label"] = r;
});

$(window).bind("load", function() {
  PeeringDB.init();
})

$(window).bind("pageshow", function() {
  PeeringDB.focus();
  const current_hash = location.hash
  if (current_hash != ""){
    const target_tab = $(`a[data-bs-toggle="tab"][href="${current_hash}"`)
    target_tab.tab("show")
  }
  $('a[data-bs-toggle="tab"]').on('shown.bs.tab', function (e) {
    const target = e.target.getAttribute("href")
    if (target !== null) location.hash = target
    PeeringDB.focus()
  });
})


/**
 * Collects and returns the data from the multiple tables to be exported
 * This is currently only relevant for campus exports.
 *
 * @param {String} container_name
 * @param {String} row_name
 * @returns
 */

function extractMultipleTableForExport(container_name,row_name) {
  let max_table = 10
  let table = 1
  let list_container = []
  let list_row = []
  let result = {}
  while(true){
    if (table > max_table) break
    if ($(`#api-listing-${container_name}${table}`).length !=0){
      list_container.push(`${container_name}${table}`)
      list_row.push(`${row_name}${table}`)
    }
    table+=1
  }
  list_container.forEach((v,i) => {
    table_name = $(`#api-listing-${v}`).find(".table-name").text().trim()
    table_result = extractFromTableForExport(v,list_row[i])
    result[table_name] = table_result
  })
  return result

}

/**
 * Collects and returns the data from the table to be exported
 *
 * @param {String} container_name
 * @param {String} row_name
 * @returns
 */

function extractFromTableForExport(container_name,row_name) {
  // collecting data from a table to be exported
  result = []
  container_selector = $(`#api-listing-${container_name}`)
  header = container_selector.find(".row.header")
  rows = container_selector.find(`#list-${row_name}`)
  keys = header.find("[data-sort-target], [data-export-field-header]").map((i,v)=>{
    if($(v).attr("id") !== "filter-web"){
      let fieldClass = $(v).attr("data-sort-target") ? $(v).attr("data-sort-target") : $(v).attr("data-export-field-header")
      return {label: $(v).text().trim(), field: fieldClass}
    }
  })

  console.log("EXTRACT", {container_name, row_name, keys})
  rows.find(".row.item, .row.sub").each((i,v)=>{
    data = {};
    x=0;

    for(let key of keys){

      // clone field
      let field = $(v).find(`${key.field}`).clone()

      // remove edit toggled fields and values so they are not included in the export
      // as tex() will pick them up even though they are display:none
      field.find("[data-edit-toggled=edit]").remove()

      // retrieve content as text
      value = field.text().trim()

      value = value.replace(/[\r\n\t×]/g, "");
      value = value.replace(/\s+/g, ' ');
      data[key.label] = value.trim();
    }
    result.push(data)
  })
  return result
}

  /**
   * Flatten a nested object
   *
   * @function flattenObject
   * @param {Object} obj - The object to flatten
   */

  flattenObject = (obj) => {
    let flattenKeys = {};
    for (let i in obj) {
        if (!obj.hasOwnProperty(i)) continue;
        if ((typeof obj[i]) == 'object') {
            let flatObject = flattenObject(obj[i]);
            for (let j in flatObject) {
                if (!flatObject.hasOwnProperty(j)) continue;
                flattenKeys[i + '.' + j] = flatObject[j];
            }
        } else {
            flattenKeys[i] = obj[i];
        }
    }
    return flattenKeys;
}

/**
 * Convert a flattened object to a CSV string
 *
 * This supports the following structures in the flattened object keys:
 *
 * - {Type}.{Column}
 * - {Type}.{Row Index}.{Column}
 * - {Type}.{Group Name}.{Row Index}.{Column}
 *
 * @function convertObjectToCSV
 * @param {Object} data - The flattened object to convert, as returned from flattenObject
 */

const convertObjectToCSV = (data, groupName) => {

  if(!groupName){
    groupName = 'group';
  }

  // Helper function to split the key and extract relevant parts
  const splitKey = (key) => {
      const parts = key.split('.');
      // Check if the key includes a group and an index
      if (parts.length >= 4) {
          return {
              group: parts[1],
              rowIndex: parts[2],
              column: parts.slice(3).join('.')
          };
      } else if( parts.length == 3) {
          return {
              group: '',
              rowIndex: parts[1],
              column: parts.slice(2).join('.')
          };
      } else {
          // Handle simpler structure without group and index
          return { group: '', rowIndex: null, column: parts.slice(1).join('.') };
      }
  };

  // Process the object to transform into rows and track unique columns
  let rows = {};
  let columns = new Set();
  for (const key in data) {
      const { group, rowIndex, column } = splitKey(key);
      columns.add(column);

      // Create a unique key for each row, considering both structures
      let rowKey = group ? group : 'default';

      if(rowIndex !== null) {
        rowKey = `${rowKey}_${rowIndex}`
      }

      if (!rows[rowKey]) {
          rows[rowKey] = { group };
      }
      rows[rowKey][column] = data[key];
  }

  const hasGroup = Object.values(rows).some(row => row.group);

  // Create the header row
  if(hasGroup){
    // Adding 'group' as the first column
    columns = [groupName, ...columns];
  } else {
    columns = [...columns];
  }
  const csvHeader = columns.join(',');

  // Create each row
  const csvRows = Object.entries(rows).map(([_, values]) => {
      return columns.map(column => {

          if(column == groupName) {
            column = 'group';
          }

          const value = values[column];
          if (typeof value === 'string' && value.includes(',')) {
              return `"${value}"`;
          }
          return value || ''; // Handle missing data with empty string
      }).join(',');
  });

  // Combine header and rows
  const csvContent = [csvHeader, ...csvRows].join('\n');

  return csvContent;
};

/**
 * Generate and download export files
 *
 * @function exportData
 * @param {Object} data
 * @param {Array} outputFormats
 * @param {String} refTag
 */

function exportData(data, outputFormats, refTag) {
  if (outputFormats.includes('JSON')) {
    const jsonData = JSON.stringify(data, null, 2);
    const jsonBlob = new Blob([jsonData], { type: 'application/json' });
    const jsonLink = document.createElement('a');
    jsonLink.href = URL.createObjectURL(jsonBlob);
    jsonLink.download = 'export.json';
    jsonLink.click();
  }

  if (outputFormats.includes('CSV')) {
    data = flattenObject(data)
    let csvData = convertObjectToCSV(data, refTag);
    const csvBlob = new Blob([csvData], { type: 'text/csv' });
    const csvLink = document.createElement('a');
    csvLink.href = URL.createObjectURL(csvBlob);
    csvLink.download = 'export.csv';
    csvLink.click();
  }
}

function getSectionDataForExport(fields, refTag) {
  let data = {};

  // Iterate over each section
  $(".export-section").each((i, section) => {
      const sectionName = $(section).find('input').val()
      const exportRowName = $(section).data("export-row-name");
      const exportContainerName = $(section).data("export-container-name");
      const extractionMethod = $(section).data("export-method");
      // Check if the current section is among the fields to be exported
      if (fields.includes(sectionName) || fields.includes("All")) {
          let result = {};

          // exclude "All" and "JSON" and "CSV" from the fields

          if (sectionName === "All" || sectionName === "JSON" || sectionName === "CSV") {
              return;
          }
          if (extractionMethod === "single-table") {
              result = extractFromTableForExport(exportContainerName, exportRowName);
          } else if (extractionMethod === "multiple-tables") {
              result = extractMultipleTableForExport(exportContainerName, exportRowName);
          } else if (extractionMethod === "object") {
            if(exportRowName == refTag) {
              // Campus from old method
              let section = $(`#${refTag}_section`).children();
              let name = $(`[data-edit-name="name"]`)
              if(name)
                result["Name"] = name[0].innerText.trim()

              section.each((i, v) => {
                let key = $(v).find('.view_field:not([style*="display:none"])').first().text().trim();
                if (key === "Geocode"){
                  let latitude =  $(v).find('[data-edit-name="latitude"]').first().text().trim();
                  let longitude =  $(v).find('[data-edit-name="longitude"]').first().text().trim();
                  value = `${latitude}, ${longitude}`
                }else{
                  value = $(v).find('.view_value:not([style*="display:none"])').first().text().trim();
                }
                value = value.replace(/[\r\n\t]/g, "")
                value = value.replace(/\s+/g, ' ')
                if (key != "") {
                  result[key] = value;
                }
              });
            }

          }

          data[sectionName] = result;
      }
  });

  return data;
}

$(document).ready(function () {
  $('#btn-export').on('click', function () {
    exportOptions = [];
    outputFormats = [];

    const refTag = $('[data-ref-tag]').data('ref-tag');

    updateSelectedOptions('#export-field input[type="checkbox"]', exportOptions);
    updateSelectedOptions('#export-format input[type="checkbox"]', outputFormats);
    const filteredData = getSectionDataForExport(exportOptions, refTag)
    exportData(filteredData, outputFormats, refTag);
  });

  function updateSelectedOptions(selector, optionsArray) {
    $(selector).each(function () {
      if ($(this).prop('checked')) {
        optionsArray.push($(this).val());
      }
    });
  }

});

$(document).ready(function () {
  var modal = $('#modalExport');

  $('#dropdownMenuLinked').click(function() {
    modal.modal('show');
  });

  modal.on("hidden.bs.modal", function () {
    $("#modalExport input[type='checkbox']").each(function() {
      $(this).prop("checked",false)
      $(this).prop("disabled",false)
    });
  });
});

/**
 * Get the value of a specific cookie by its name.
 *
 * Splits the document's cookies into key-value pairs and searches for the specified cookie name.
 * Returns the value of the cookie if found, or null if it does not exist.
 *
 * @function getCookieValue
 * @param {string} name - The name of the cookie to retrieve.
 * @returns {string|null} The value of the cookie, or null if not found.
 */
function getCookieValue(name) {
  const cookies = document.cookie.split('; ');
  for (const cookie of cookies) {
    const [key, val] = cookie.split('=');
    if (key === name) return val;
  }
  return null;
}

/**
 * Update the `src` attribute of an image element based on a suffix.
 *
 * Replaces the current suffix of the image's `src` (e.g., `-dark` or no suffix) with the provided suffix.
 *
 * @function updateImageSrc
 * @param {HTMLImageElement|null} element - The image element to update.
 * @param {string} suffix - The suffix to append to the image filename (e.g., `-dark` or an empty string).
 */
function updateImageSrc(element, suffix) {
  if (element && element.src) {
    element.src = element.src.replace(/(-dark)?\.png$/, suffix + '.png');
  }
}

/**
 * Update the `src` attributes of all relevant images based on the theme mode.
 *
 * Determines the suffix based on whether dark mode is enabled and updates:
 * - The logo image
 *
 * @function updateImages
 * @param {boolean} isDark - Whether dark mode is active.
 */
function updateImages(isDark) {
  const suffix = isDark ? '-dark' : '';
  updateImageSrc(document.getElementById('logo'), suffix);
  updateImageSrc(document.getElementById('hamburger'), suffix);
}

/**
 * Set the theme mode and update the UI accordingly.
 *
 * Determines the active theme mode (`light`, `dark`, or `auto`) and applies the necessary changes:
 * - Saves the theme preference and mode in cookies
 * - Updates the `data-theme` attribute on the document
 * - Adjusts images for the selected mode
 *
 * @function setMode
 * @param {string} mode - The theme mode to set (`light`, `dark`, or `auto`).
 */
function setMode(mode) {
  const darkThemeMq = window.matchMedia('(prefers-color-scheme: dark)');
  const isDark = mode === 'dark' || (mode === 'auto' && darkThemeMq.matches);

  document.cookie = `theme=${mode}; path=/; max-age=31536000`;
  document.cookie = `is_dark_mode=${isDark}; path=/; max-age=31536000`;

  document.documentElement.dataset.theme = isDark ? 'dark' : 'light';

  updateImages(isDark);
}

/**
 * Initialize the theme on page load.
 *
 * Reads the saved theme mode from cookies (or defaults to `light`), determines if dark mode should be enabled,
 * and updates the UI accordingly.
 *
 * @function initializeTheme
 */
function initializeTheme() {
  const mode = getCookieValue('theme') || 'light';
  const darkThemeMq = window.matchMedia('(prefers-color-scheme: dark)');
  const isDark = mode === 'dark' || (mode === 'auto' && darkThemeMq.matches);

  document.documentElement.dataset.theme = isDark ? 'dark' : 'light';
  updateImages(isDark);
}

// Ensure the theme is initialized when the DOM is fully loaded and respond to system theme changes.
document.addEventListener('DOMContentLoaded', () => {
  initializeTheme();

  const darkThemeMq = window.matchMedia('(prefers-color-scheme: dark)');
  darkThemeMq.addEventListener('change', (e) => {
    const mode = getCookieValue('theme');
    if (mode === 'auto') {
      const isDark = e.matches;
      document.cookie = `is_dark_mode=${isDark}; path=/; max-age=31536000`;
      document.documentElement.dataset.theme = isDark ? 'dark' : 'light';
      updateImages(isDark);
    }
  });
});

/**
 * Set up the theme container, tooltips, and theme mode buttons.
 *
 * Initializes theme-related functionality when the DOM is fully loaded.
 * - Configures Bootstrap tooltips for elements within the `.theme-container`.
 * - Updates the active state of theme mode buttons (`light`, `dark`, `auto`).
 * - Listens for clicks on theme mode buttons to update the UI accordingly.
 *
 * @function DOMContentLoaded
 */
document.addEventListener("DOMContentLoaded", () => {
  /**
   * Initialize Bootstrap tooltips within the theme container.
   *
   * Finds all elements in the `.theme-container` with the `data-bs-toggle="tooltip"` attribute
   * and applies Bootstrap's tooltip functionality to them.
   */
  const themeContainer = document.querySelector('.theme-container');
  if (themeContainer) {
      const tooltipTriggerList = [].slice.call(themeContainer.querySelectorAll('[data-bs-toggle="tooltip"]'));
      tooltipTriggerList.forEach(tooltipTriggerEl => {
          new bootstrap.Tooltip(tooltipTriggerEl);
      });
  }

  /**
   * Update the active state of theme mode buttons.
   *
   * Reads the current theme mode from cookies and applies the `active` class to the corresponding button.
   * Removes the `active` class from all other buttons.
   *
   * @function updateActiveButton
   */
  function updateActiveButton() {
      const mode = getCookieValue('theme') || 'light';
      const buttons = {
          light: document.getElementById('light-mode-btn'),
          dark: document.getElementById('dark-mode-btn'),
          auto: document.getElementById('auto-mode-btn')
      };
      Object.values(buttons).forEach(btn => btn.classList.remove('active'));
      if (buttons[mode]) {
          buttons[mode].classList.add('active');
      }
  }

  // Initialize the theme mode and set the active button state.
  initializeTheme();
  updateActiveButton();

  /**
   * Listen for theme mode button clicks and update the UI.
   *
   * Attaches a click event listener to the `.btn-group` container. If a button inside
   * the group is clicked, it triggers `updateActiveButton` to reflect the change in the UI.
   */
  const btnGroup = document.querySelector('.btn-group');
  if (btnGroup) {
      btnGroup.addEventListener('click', (e) => {
          if (e.target.tagName === 'BUTTON') {
              updateActiveButton();
          }
      });
  }
});

/**
 * Prevents category-view flash during pagination while in list-view
 */
(function() {
  const savedMode = localStorage.getItem("searchViewMode");
  if (savedMode === "list") {
    document.write('<style id="view-state">' +
      '#search-list-view { display: block !important; }' +
      '#search-category-view { display: none !important; }' +
    '</style>');
  }
})();

/**
 * Search results view switching functionality
 *
 * These functions handle visibility switching between two view modes:
 * - List view: Shows search results in a single column list format
 * - Category view: Shows search results grouped by entity types in multiple columns
 *
 * The view state is persisted in localStorage and button text updates to reflect current state:
 * - In list view: Button shows "Switch to Category View"
 * - In category view: Button shows "Switch to List View"
 */

/**
 * Sets display mode and updates UI elements for search result
 * @param {string} mode - View mode to set ('list' or 'category')
 */
function setViewMode(mode) {
  const $listView = $("#search-list-view");
  const $categoryView = $("#search-category-view");
  const $toggleText = $("#search-toggle-text");
  if (mode === "list") {
      $listView.show();
      $categoryView.hide();
      $toggleText.text($toggleText.data("category-view"));
  } else {
      $listView.hide();
      $categoryView.show();
      $toggleText.text($toggleText.data("list-view"));
  }
  localStorage.setItem("searchViewMode", mode);
}

/**
* Toggles between view modes based on current visibility
* @listens click - Triggered by #search-change-view button
*/
function toggleSearchView() {
  const $categoryView = $("#search-category-view");
  const viewMode = $categoryView.is(":visible") ? "list" : "category";
  setViewMode(viewMode);
}

/**
 * Initialize the search view toggle functionality when document is ready
 * Restores the last active view mode from localStorage or defaults to category view
 */
$(function() {
  $("#search-change-view").on("click", toggleSearchView);

  // Set initial view state
  const savedMode = localStorage.getItem("searchViewMode");
  setViewMode(savedMode || "category");

  // Clean up the early injection
  $("#view-state").remove();
});
