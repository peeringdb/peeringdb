(function($) {

/**
 * peeringdb admin tools
 */

PeeringDBAdmin = {

  init : function() {
    if($('#org-merge-tool').length > 0)
      this.OrgMergeTool.init();
  },

  OrgMergeTool : {
    tool : function() {
      return $('#org-merge-tool')
    },
    init : function() {
      this.tool().find("#org-autocomplete-search-src").yourlabsAutocomplete({
        url : "/autocomplete/org",
        minimumCharacters : 2,
        choiceSelector : "span",
        inputClick : function(e,a,b) { console.log(e, a, b); }
      }).input.bind("selectChoice", function(a,b) {
        console.log("Selected Source Org", b.data("value"));
        PeeringDBAdmin.OrgMergeTool.addToSelected(b.data("value"), b.text());
        $(this).val("")
      });

      this.tool().find("#org-autocomplete-search-trg").yourlabsAutocomplete({
        url : "/autocomplete/org",
        minimumCharacters : 2,
        choiceSelector : "span",
        inputClick : function(e,a,b) { console.log(e, a, b); }
      }).input.bind("selectChoice", function(a,b) {
        console.log("Selected Target Org", b.data("value"));
        PeeringDBAdmin.OrgMergeTool.setTargetOrg(b.data("value"), b.text());
        $(this).val("")
      });

      this.tool().find('#btn-submit').click(function() {
        PeeringDBAdmin.OrgMergeTool.submit();
      });
    },

    // crude server error notification
    error : function(response) {
      alert("Server responded with error, please check console for further details");
      console.error(response);
    },

    // reset all selections
    reset : function() {
      this.tool().find('#listing-selected').empty().siblings(".loading-shim").show();
      this.setTargetOrg();
    },

    // submit merge request
    submit : function() {
      var orgs = [];
      this.tool().find('.error-message').hide()
      this.tool().children(".loading-shim").show();
      this.tool().find('#listing-selected').find('.row').each(function(){
        orgs.push(parseInt($(this).data("id")));
      });
      $.ajax({
        url : "merge",
        method : "GET",
        data : {
          "ids" : orgs.join(","),
          "id" : this.targetOrgId
        },
        success : function(data) {
          this.tool().children(".loading-shim").hide();

          if(data.error) {
            this.tool().find('.error-message').empty().show().text(data.error)
            return
          }

          PeeringDBAdmin.OrgMergeTool.stats(data);
          PeeringDBAdmin.OrgMergeTool.reset();
        }.bind(this)
      }).fail(function(response) {
        PeeringDBAdmin.OrgMergeTool.error(response);
        this.tool().children(".loading-shim").hide();
      }.bind(this));
    },

    // render the stats returned by the merge request
    stats : function(data) {
      var sn = this.tool().find('#stats').empty()
      var i;
      for(i in data) {
        sn.append($('<div>').text(i+': '+data[i]))
      }
    },

    // remove org from selected org list
    removeFromSelected : function(id, name) {
      this.tool().find('#listing-selected').find('[data-id="'+id+'"]').detach();
    },

    // add org to selected org list
    addToSelected : function(id, name) {
      var tool = this.tool();
      if(this.targetOrgId == id) {
        return alert("Merge Target cannot be in selected list")
      }
      var row = $('<div>')
        .addClass('row')
        .attr('data-id', id)
        .text(name)
      row.click(function() { PeeringDBAdmin.OrgMergeTool.removeFromSelected(id, name) });
      tool.find('#listing-selected').append(row);
      tool.find('#listing').find('[data-id="'+id+'"]').detach();
    },

    // set target org
    setTargetOrg : function(id, name) {
      var tool = this.tool()
      if(!id) {
        tool.find('#target-org-help').show();
        tool.find('#target-org').empty();
        tool.find('.finalize').hide();
      } else {
        tool.find('#target-org-help').hide();
        tool.find('#target-org').text(name);
        tool.find('.finalize').show();
        this.targetOrgId = parseInt(id);
        this.removeFromSelected(this.targetOrgId);

      }
    }
  }
}

twentyc.editable.target.register(
  "merge-organization",
  {
    execute : function(a,b,c) {
      console.log(a,b,c);
      console.log(this);
    }
  },
  "base"
);

$(window).ready(function() {
  PeeringDBAdmin.init();
});

})(jQuery);
