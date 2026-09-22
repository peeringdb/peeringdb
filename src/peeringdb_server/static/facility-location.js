(function ($) {
  "use strict";

  const fields = ["address1", "city", "state", "zipcode", "country", "latitude", "longitude"];
  let mapsPromise;

  function loadMaps(key) {
    if (window.google && google.maps && google.maps.importLibrary) {
      return Promise.resolve();
    }
    if (!mapsPromise) {
      mapsPromise = new Promise((resolve, reject) => {
        if (!key) return reject(new Error("maps"));
        const script = document.createElement("script");
        const timeout = setTimeout(() => reject(new Error("maps")), 10000);
        window.facilityLocationMapsReady = () => { clearTimeout(timeout); resolve(); };
        script.onerror = () => { clearTimeout(timeout); reject(new Error("maps")); };
        script.src = "https://maps.googleapis.com/maps/api/js?" + new URLSearchParams({
          key: key, v: "weekly", loading: "async", callback: "facilityLocationMapsReady"
        });
        document.head.appendChild(script);
      }).catch(error => { mapsPromise = null; throw error; });
    }
    return mapsPromise;
  }

  function errorText(error) {
    if (error.status === 409) return gettext("The facility location changed. Reload and select it again.");
    const body = error.responseJSON;
    if (body && error.status === 400) {
      return Object.keys(body).filter(key => key !== "meta").map(key => String(body[key])).join(" ") || gettext("Select another location or contact support.");
    }
    return gettext("Location lookup is unavailable. Retry, choose on map, or email support.");
  }

  class Chooser {
    constructor(element) {
      this.element = $(element);
      this.container = this.element.closest("[data-edit-target]");
      this.country = this.element.find(".location-country");
      this.search = this.element.find(".location-search");
      this.results = this.element.find(".location-results");
      this.message = this.element.find(".location-message");
      this.proposalBox = this.element.find(".location-proposal");
      this.confirm = this.element.find(".location-confirm");
      this.initialCountry = this.element.attr("data-country") || "";
      this.facilityId = Number(this.element.attr("data-facility-id")) || null;
      this.version = this.element.attr("data-location-version");
      this.sequence = 0;
      this.reset();
      this.search.on("input", () => {
        this.invalidate();
        this.mapMode = false;
        this.updateSupport();
        const sequence = this.sequence;
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.lookup(sequence), 300);
      });
      this.search.on("keydown", event => {
        if (event.key === "Enter") { event.preventDefault(); event.stopPropagation(); }
        if (event.key === "ArrowDown") { event.preventDefault(); this.results.find("button").first().trigger("focus"); }
      });
      this.country.on("change", () => {
        const mapOpen = this.mapMode || this.element.find(".location-map").is(":visible");
        this.invalidate();
        this.pin = null;
        this.countryChanged = true;
        this.element.find(".location-map").hide();
        if (this.marker) this.marker.map = null;
        this.sessionToken = crypto.randomUUID();
        this.mapMode = false;
        this.updateSupport();
        if (mapOpen && this.country.val()) this.chooseMap();
        this.lookup(this.sequence);
      });
      this.element.find(".location-map-choice").on("click", () => this.chooseMap());
      this.element.find(".location-open").on("click", () => {
        this.element.find(".location-editor").prop("hidden", false);
        this.element.find(".location-open").prop("hidden", true).attr("aria-expanded", "true");
        this.search.trigger("focus");
      });
      this.element.find(".location-reset").on("click", () => {
        this.reset();
        this.element.find(this.facilityId ? ".location-open" : ".location-country").trigger("focus");
      });
      this.results.on("keydown", "button", event => {
        const buttons = this.results.find("button");
        const index = buttons.index(event.currentTarget);
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          const next = index + (event.key === "ArrowDown" ? 1 : -1);
          if (next < 0) this.search.trigger("focus");
          else buttons.eq(Math.min(next, buttons.length - 1)).trigger("focus");
        } else if (event.key === "Escape") {
          event.preventDefault();
          this.search.trigger("focus");
        }
      });
      this.confirm.on("click", () => {
        if (!this.proposal) return;
        this.confirmed = this.proposal;
        this.previewLocation(this.confirmed.location);
        this.confirm.prop("disabled", true);
        this.container.data("edit-changed", "yes");
        this.message.text(gettext("Location confirmed. Save the form to apply it."));
      });
      this.element.find(".location-support").on("click", () => this.updateSupport());
      this.container.on("edit-cancel", event => { if (event.target === this.container[0]) this.reset(); });
      this.container.on("action-success:submit", (event, data) => {
        if (event.target !== this.container[0]) return;
        if (this.facilityId) {
          window.location.reload();
        } else {
          this.reset();
        }
      });
      this.container.on("export", (event, data) => {
        if (event.target === this.container[0] && this.dirty) data._changed = true;
      });
    }

    invalidate() {
      this.restoreLocationPreview();
      this.sequence++;
      this.dirty = true;
      this.proposal = null;
      this.confirmed = null;
      this.saveErrorMessage = null;
      this.results.empty();
      this.proposalBox.prop("hidden", true);
      this.confirm.prop("disabled", true);
      this.element.find(".location-provider-attributions").empty();
      this.message.empty();
      this.element.find(".location-point").empty();
    }

    restoreLocationPreview() {
      (this.previewFields || []).forEach(({element, content}) => element.empty().append(content));
      this.previewFields = [];
      if (this.previewCells) {
        this.previewCells.removeClass("location-pending").children(".location-pending-label").remove();
      }
    }

    previewLocation(values) {
      this.restoreLocationPreview();
      this.previewCells = $();
      const previewValues = Object.assign({}, values);
      const region = this.country.find(":selected").attr("data-region");
      if (region) previewValues.region_continent = region;
      Object.keys(previewValues).forEach(field => {
        this.container.find('[data-edit-name="' + field + '"], [data-location-field="' + field + '"]').each((index, node) => {
          const element = $(node);
          this.previewFields.push({element: element, content: element.contents().detach()});
          element.text(previewValues[field] === "" ? gettext("Not provided") : String(previewValues[field]));
          const cell = element.closest(".view_value");
          this.previewCells = this.previewCells.add(cell.length ? cell : element.parent());
        });
      });
      const preview = this.container.find("#geocode_preview");
      if (preview.length) {
        this.previewFields.push({element: preview, content: preview.contents().detach()});
        preview.append($("<a>", {
          href: "https://maps.google.com/?q=" + values.latitude + "," + values.longitude,
          target: "_blank", rel: "noopener noreferrer", text: gettext("Preview in Google Maps")
        }));
      }
      this.previewCells.addClass("location-pending").append(() => $("<span>", {
        class: "location-pending-label", text: gettext("Pending Save")
      }));
    }

    reset() {
      this.invalidate();
      clearTimeout(this.timer);
      this.dirty = false;
      this.mapMode = false;
      this.pin = null;
      this.countryChanged = false;
      this.sessionToken = crypto.randomUUID();
      this.search.val("");
      this.country.val(this.initialCountry);
      this.element.find(".location-point").empty();
      this.element.find(".location-map").hide();
      this.element.find(".location-editor").prop("hidden", Boolean(this.facilityId));
      this.element.find(".location-open").prop("hidden", false).attr("aria-expanded", "false");
      this.updateSupport();
    }

    target() {
      const target = {ref_tag: "fac", org_id: Number(this.element.attr("data-org-id")), country: this.country.val()};
      if (this.facilityId) Object.assign(target, {ref_id: this.facilityId, location_version: this.version});
      return target;
    }

    request(endpoint, data) {
      return $.ajax({url: "/data/location/" + endpoint, method: "POST", contentType: "application/json", data: JSON.stringify(Object.assign(this.target(), data))});
    }

    lookup(sequence) {
      if (sequence !== this.sequence) return;
      const input = this.search.val().trim();
      if (!this.country.val()) {
        this.message.text(gettext("Select a country first."));
        return;
      }
      if (input.length < 2) return;
      this.message.text(gettext("Searching…"));
      this.request("search", {input: input, session_token: this.sessionToken}).done(response => {
        if (sequence !== this.sequence) return;
        const suggestions = response.suggestions;
        this.results.empty();
        this.message.text(suggestions.length ? gettext("Select a result to review its address.") : gettext("No matching location. Try another search or choose on map."));
        suggestions.forEach(suggestion => {
          const button = $("<button>", {type: "button", class: "location-result", text: suggestion.label});
          button.on("click", () => this.select(suggestion));
          this.results.append($("<li>").append(button));
        });
      }).fail(error => { if (sequence === this.sequence) this.message.text(errorText(error)); });
    }

    select(suggestion) {
      this.invalidate();
      this.mapMode = false;
      this.search.val(suggestion.label);
      const sessionToken = this.sessionToken;
      this.sessionToken = crypto.randomUUID();
      this.resolve({place_id: suggestion.place_id, session_token: sessionToken});
    }

    async showMap(point, sequence, viewport) {
      await loadMaps(this.element.attr("data-maps-key"));
      const {Map} = await google.maps.importLibrary("maps");
      const {AdvancedMarkerElement} = await google.maps.importLibrary("marker");
      if (sequence !== this.sequence) return;
      const mapElement = this.element.find(".location-map").show()[0];
      if (!this.map) {
        this.map = new Map(mapElement, {center: point, zoom: 3, mapId: this.element.attr("data-map-id") || "DEMO_MAP_ID", streetViewControl: false});
        this.marker = new AdvancedMarkerElement({map: this.map, position: point, title: gettext("Facility location"), gmpDraggable: true});
        this.map.addListener("click", event => { if (this.mapMode && event.latLng) this.movePin(event.latLng.toJSON()); });
        this.marker.addListener("dragstart", () => this.invalidate());
        this.marker.addListener("dragend", () => {
          const position = this.marker.position;
          this.movePin(typeof position.toJSON === "function" ? position.toJSON() : position);
        });
      }
      this.marker.gmpDraggable = this.mapMode;
      this.marker.map = viewport ? null : this.map;
      this.marker.position = point;
      if (viewport) this.map.fitBounds(viewport);
      else {
        this.map.setCenter(point);
        this.map.setZoom(this.pin || this.proposal ? 16 : 3);
      }
    }

    async chooseMap() {
      this.invalidate();
      this.mapMode = true;
      if (!this.country.val()) {
        this.message.text(gettext("Select a country first."));
        return;
      }
      const savedLat = this.element.attr("data-latitude");
      const savedLng = this.element.attr("data-longitude");
      const lat = Number(savedLat);
      const lng = Number(savedLng);
      const useSaved = !this.countryChanged && this.country.val() === this.initialCountry && savedLat && savedLng && Number.isFinite(lat) && Number.isFinite(lng);
      const point = this.pin || (useSaved ? {lat: lat, lng: lng} : null);
      const sequence = this.sequence;
      this.message.text(gettext("Click the map or move the pin to select the facility. You can also drag the pin with the keyboard."));
      try {
        if (point) await this.showMap(point, sequence);
        else {
          const response = await this.request("country", {});
          if (sequence !== this.sequence) return;
          const bounds = response.viewport;
          await this.showMap({lat: 0, lng: 0}, sequence, bounds);
        }
      }
      catch (error) { if (sequence === this.sequence) this.message.text(gettext("The map could not be loaded. Retry or email support.")); }
    }

    movePin(point) {
      this.invalidate();
      this.mapMode = true;
      this.pin = {lat: Number(point.lat.toFixed(6)), lng: Number(point.lng.toFixed(6))};
      this.marker.map = this.map;
      this.marker.position = this.pin;
      this.element.find(".location-point").text(this.pin.lat + ", " + this.pin.lng);
      this.resolve({latitude: this.pin.lat, longitude: this.pin.lng});
    }

    resolve(selection) {
      const sequence = this.sequence;
      this.message.text(gettext("Resolving location…"));
      this.updateSupport();
      this.request("resolve", selection).done(async response => {
        if (sequence !== this.sequence) return;
        this.proposal = response;
        const values = this.proposal.location;
        this.pin = {lat: values.latitude, lng: values.longitude};
        const labels = [gettext("Address"), gettext("City"), gettext("State / Province"), gettext("Postal code"), gettext("Country"), gettext("Latitude"), gettext("Longitude")];
        const details = this.element.find(".location-details").empty();
        fields.forEach((field, index) => details.append($("<dt>").text(labels[index]), $("<dd>").text(values[field] === "" ? gettext("Not provided") : String(values[field]))));
        (this.proposal.attributions || []).forEach(attribution => {
          const name = attribution.provider || "";
          const uri = attribution.providerUri || "";
          const item = /^https?:\/\//.test(uri) ? $("<a>", {href: uri, target: "_blank", rel: "noopener noreferrer"}).text(name) : $("<span>").text(name);
          this.element.find(".location-provider-attributions").append(item, document.createTextNode(" "));
        });
        this.proposalBox.prop("hidden", false);
        this.confirm.prop("disabled", false);
        this.message.text(gettext("Review these exact values before confirming. If they are wrong, choose on map or email support."));
        this.element.find(".location-point").text(values.latitude + ", " + values.longitude);
        this.updateSupport();
        try { await this.showMap(this.pin, sequence); }
        catch (error) { if (sequence === this.sequence) this.message.text(gettext("The map could not be loaded. Review the resolved address and coordinates, retry, or email support.")); }
      }).fail(error => { if (sequence === this.sequence) this.message.text(errorText(error)); });
    }

    updateSupport() {
      const name = this.container.find('[data-edit-name="name"]');
      const facilityName = name.find("input").val() || name.text().trim();
      const body = "Facility: " + (this.facilityId || facilityName || "") + "\nEntered address: " + this.search.val() + "\nSelected point: " + (this.pin ? this.pin.lat + ", " + this.pin.lng : "") + "\nWhat needs correcting: ";
      this.element.find(".location-support").attr("href", "mailto:" + this.element.attr("data-support") + "?subject=" + encodeURIComponent("Facility address assistance") + "&body=" + encodeURIComponent(body));
    }

    saveFailed(error) {
      const body = error.responseJSON || {};
      const locationErrors = fields.concat(["location", "location_confirmation"])
        .filter(field => body[field]);
      let message;
      if (error.status === 409) {
        message = body.detail || gettext("The facility location changed. Reload and select it again.");
      } else if (error.status === 400 && locationErrors.length) {
        const messages = locationErrors.flatMap(field => [].concat(body[field]).map(String));
        message = Array.from(new Set(messages)).join(" ");
        if (!body.location_confirmation) message += " " + gettext("Select another location or email support.");
      } else {
        return;
      }
      this.invalidate();
      this.saveErrorMessage = message;
      this.message.text(message);
    }

    prepare(data) {
      if (!this.confirmed && (this.dirty || !this.facilityId)) {
        this.message.text(this.saveErrorMessage || gettext("Select and confirm a location, or cancel the location change."));
        return false;
      }
      fields.forEach(field => delete data[field]);
      if (this.confirmed) {
        Object.assign(data, this.confirmed.location);
      }
      return true;
    }
  }

  window.FacilityLocation = {
    prepare(sender, data) {
      const chooser = $(sender).find(".facility-location").data("location-chooser");
      return !chooser || chooser.prepare(data);
    },
    request(sender, method, endpoint, id, data, success) {
      const chooser = $(sender).find(".facility-location").data("location-chooser");
      if (!chooser || !chooser.confirmed) return PeeringDB.API.request(method, endpoint, id, data, success);
      const confirmed = chooser.confirmed;
      return $.ajax({
        url: "/data/location/save", method: method, contentType: "application/json", dataType: "json", success: success,
        data: JSON.stringify(Object.assign(chooser.target(), {location_confirmation: confirmed.location_confirmation, data: data}))
      }).fail(error => { if (chooser.confirmed === confirmed) chooser.saveFailed(error); });
    }
  };
  $(function () {
    $(".facility-location").each(function () { $(this).data("location-chooser", new Chooser(this)); });
  });
})(jQuery);
