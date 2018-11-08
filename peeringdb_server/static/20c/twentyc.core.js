(function() {

/**
 * create root namespace for all twentyc definitions
 * @module twentyc
 */

twentyc = {};

/**
 * class helper functions
 * @module twentyc
 * @class cls
 * @static
 */

/// Contains 7 sentences fo devs, no need for translation

twentyc.cls = {

  /**
   * converts a string into a standardized class name, replacing
   * invalid characters with valid ones.
   *
   *     twentyc.cls.make_name("class-a"); // classA
   *     twentyc.cls.make_name("class a b"); // classAB
   *     twentyc.cls.make_name("Class-A_B"); // ClassA_B
   *
   * @method make_name
   * @param {String} name base name
   * @returns {String} class_name changed name
   */

  make_name : function(name) {
    var i, names = name.split(/[-\s]/);
    for(i = 0; i < names.length; i++) {
      if(i > 0)
        names[i] = names[i].charAt(0).toUpperCase() + names[i].slice(1);
    }
    return names.join("");
  },

  /**
   * create a new class - if you wish to extend a class take a look at
   * {{#crossLink "cls/extend:method"}}twentyc.cls.extend{{/crossLink}} 
   * instead
   *
   * you may define a constructor in the definition by using the class
   * name you provide at __name__
   *
   * Note that if the name you provide is not a valid variable name
   * it will be passed through twentyc.cls.make_name to make it valid
   *
   * ##examples
   *
   * * define and instantiate a class: examples/cls.define.js
   *
   * @method define
   * @param {String} name name or unique identifier of the new class
   * @param {Object} definition object literal of properties and functions that you wish define or redefine
   * @returns {Function} dest constructor of new class
   */
  
  define : function(name, definition) {

    var k;

    name = twentyc.cls.make_name(name);
    
    if(typeof(definition[name]) == "function") {
      // a constructor has been provided
      var ctor = definition[name]
      delete definition[name]
    } else {
      // no constructor provided, substitute empty constructor
      var ctor = function(){};
    }

    // cycle through definition and copy to class prototype
    for(k in definition) {
      ctor.prototype[k] = definition[k]
    }

    // create meta information
    ctor.prototype._meta = {
      "name" : name
    }

    return ctor

  },
  
  /**
   * extend an existing class with new properties and functions
   *
   * if a function is defined that already exists on the parent class
   * this function will be overwritten and a reference to the original
   * function will be provided at parentClassName_functionName
   *
   * you may define a constructor in the definition by using the class
   * name you provide at __name__
   *
   * Note that if the name you provide is not a valid variable name
   * it will be passed through twentyc.cls.make_name to make it valid
   *
   * ##examples
   * 
   * * extend and instantiate a class: examples/cls.extend.js
   * * handling method override: examples/cls.extend.method-override.js
   *
   * @method extend
   * @param {String} name name or unqiue identifier of the new class
   * @param {Object} definition object literal of properties and functions that you wish define or redefine
   * @param {Function} [parent] constructor of class 
   * that you wish to extend, if omitted an empty function will be substituted
   * @returns {Function} dest constructor of new class
   */

  extend : function(name, definition, parent) {
    
    var k;
    name = twentyc.cls.make_name(name);
    
    if(typeof(definition[name]) == "function") {
      // a constructor has been provided
      var ctor = definition[name]
      delete definition[name]
    } else {
      // no constructor provided, substitute empty constructor
      var ctor = function(){
        parent.apply(this, arguments)
      };
    }

    // cycle through parent prototype and copy to class prototype
    for(k in parent.prototype) {
      ctor.prototype[k] = parent.prototype[k]
    }

    // cycle through definition and copy to class prototype
    for(k in definition) {
      if(typeof(ctor.prototype[k]) == "function") {
        // function was already defined by parent, store backref
        ctor.prototype[parent.prototype._meta.name+"_"+k] = parent.prototype[k];
      }
      ctor.prototype[k] = definition[k]
    }
    
    // reference parent constructor
    ctor.prototype[parent.prototype._meta.name] = parent

    // create meta information
    ctor.prototype._meta = {
      "name" : name,
      "parent" : parent
    }

    return ctor


  },

  /**
   * overrides a method on the provided class
   *
   * @method override
   * @param {Function} destClass A class created via __twentyc.cls.define__ or __twentyc.cls.extend__
   * @param {String} methodName name of method that you wish to override
   * @param {Function} method new method
   */

  override : function(destClass, methodName, method) {
    
    // create reference to old method
    if(destClass.prototype[methodName])
      destClass.prototype[destClass.prototype._meta.name+"_"+methodName] = destClass.prototype[methodName];
    
    // override
    destClass.prototype[methodName] = method;

  }

}


/**
 * class registry object - allows you to quickly define and extend
 * similar classes
 *
 * @module twentyc
 * @namespace twentyc.cls
 * @class Registry
 * @constructor
 */

twentyc.cls.Registry = twentyc.cls.define(
  "Registry",
  {
    
    Registry : function() {
      
      /**
       * holds the classes defined in this registry
       * @property _classes
       * @type Object
       * @private
       */

      this._classes = {}

    },

    /**
     * register a new class - look at twentyc.cls.define and twentyc.cls.extend for param
     * explanation
     * @method register
     * @param {String} name class name
     * @param {Object} definition class definition
     * @param {String} extend if passed, extend this class from this class (needs to exist in the Registry)
     * @returns {Function} class ctor of the newly created class
     */

    register : function(name, definition, extend) {
      if(this._classes[name] != undefined) {
        throw("Class with name '"+name+"' already exists - name must be unique in the Registry");
      }
      if(extend && typeof this._classes[extend] != "function") {
        throw("Trying to extend from class unknown to this Registry: "+extend);
      }
      if(extend)
        this._classes[name] = twentyc.cls.extend(name, definition, this._classes[extend]);
      else
        this._classes[name] = twentyc.cls.define(name, definition);
      return this._classes[name];
    },

    /**
     * get a registered class constructor
     * @method get
     * @param {String} name class name
     * @returns {Function} class ctor of registered class
     */

    get : function(name) {
      if(typeof this._classes[name] != "function") 
        throw("Trying to retrieve class unknown to this Registry: "+name);
      return this._classes[name];
    },

    /**
     * See if a class constructor for the specified name exists
     * @method has
     * @param {String} name class name
     * @returns {Boolean} exists
     */

    has : function(name) {
      return (typeof this._classes[name] == "function")
    }
  }
);

/**
 * utility functions
 * @module twentyc
 * @class util
 * @static
 */

twentyc.util = {
  
  /**
   * retrieve value from object literal - allows you to pass null or undefined
   * as the object and will return null if you do
   *
   * @method get
   * @param {Object} obj 
   * @param {String) key
   * @param {Mixed} [default] return this if obj is null or key does not exist
   * @returns {Mixed} value
   */

  get : function(obj, key, dflt) {
    if(!obj || obj[key] == undefined)
      return dflt;
    return obj[key]
  },

  /**
   * requires a namespace exist, any keys that do not exist will
   * be created as object literals
   *
   * @method require_namespace
   * @param {String} namespace "." separated namespace
   */

  require_namespace : function(namespace) {
    var tokens = namespace.split("."),
        i,
        t,
        container=window;

    for(i = 0; i < tokens.length; i++) {
      t = tokens[i];
      if(typeof container[t] == "undefined") {
        container[t] = {}
      }
      container = container[t];
    }
    return container;
  }

}

/**
 * data retrieval, storage and management
 *
 * assures that data is only retrieved once even when multiple sources
 * are requesting it. 
 *
 * data is cached locally for quick retrieval afterwards
 *
 * @module twentyc
 * @class data
 * @static
 */

twentyc.data = {

  /**
   * fires everytime a dataset is retrieved from the server - __*__ is
   * substituted with the data id
   *
   * all handlers bound to this event will be removed after its been
   * triggered - in order to permanently subscribe a load event
   * subscribe to "load"
   *
   * @event load-*
   * @param {String} id data id
   * @param {Object} data object literal of retrieved data
   */

  /**
   * fires everytime a dataset is retrieved from the server
   *
   * @event load
   * @param {String} id data id
   * @param {Object} data object literal of retrieved data
   */

  /**
   * fires when all loads are finished
   *
   * @event done
   */

  /**
   * keeps track of current loading status 
   * @property _loading
   * @type Object
   * @private
   */

  _loading : {},

  /**
   * _data storage, keyed by data id
   * @property data
   * @type Object
   * @private
   */

  _data : {},

  /**
   * attempts to retrieve and return a data set 
   *
   * ##example(s)
   *
   * examples/data.load.js
   *
   * @method get
   * @param {String} id data id
   * @returns {Object} data
   */

  get : function(id) {
    return tc.u.get(this._data, id, {})
  },

  /**
   * retrieve data from server. at this point this expects a json
   * string response, with the actual data keyed at the id you provided
   *
   * ##example(s)
   *
   * examples/data.load.js
   *
   * @method load
   * @param {String} id data identification key
   * @param {Object} [config] object literal holding options
   * @param {Function} [config.callback] called when data is available
   * @param {Boolean} [config.reload] if true data will be re-fetched even if already loaded
   */

  load : function(id, config) {
    
    var callback = tc.u.get(config, "callback");

    // check if data is already loaded
    if(this._data[id] && !tc.u.get(config, "reload")) {
      var payload = {id:id, data:this._data[id]}
      $(this).trigger("load-"+id, payload);
      if(callback)
        callback(payload)
      return;
    }

    // attach callback to load event
    if(callback) {
      $(this).on("load-"+id, function(ev, payload) { callback(payload) }); 
    }

    // check if data is currently being loaded
    if(this._loading[id]) {
      return;
    }

    // data is not loaded AND not currently loading, attempt to load data

    // in order to load data we need to find a suitable loader for it

    var loader = this.loaders.loader(id, config);
    this._loading[id] = new Date().getTime()
    loader.load(
      {
        success : function(data) {
          twentyc.data._data[id] = data
          twentyc.data._loading[id] = false;
          $(twentyc.data).trigger("load", { id:id, data:data} );
          $(twentyc.data).trigger("load-"+id, { id:id, data:data }); 
          $(twentyc.data).off("load-"+id);
          twentyc.data.done();
        }
      }
    );
  },

  done : function(callback) {
    var i;
    if(callback) {
      $(this).on("done", callback);
      $(this).on("done", function() { $(twentyc.data).off("done", callback); });
    }
    for(i in this._loading) {
      if(twentyc.data._loading[i]) {
        return;
      }
    }
    $(this).trigger("done", {});
  }

}

/**
 * create and manage data loaders
 * @module twentyc
 * @namesapce twentyc.data
 * @class loaders
 * @extends twentyc.cls.Registry
 * @static
 */

twentyc.data.LoaderRegistry = twentyc.cls.extend(
  "LoaderRegistry",
  {
    LoaderRegistry : function() {
      this.Registry();

      /**
       * holds data id -> loader assignments, keyed by data id
       * @property _loaders
       * @type Object
       * @private
       */

      this._loaders = {};
    },

    /**
     * assign loader to data id
     * @method assign
     * @param {String} id data id
     * @param {String} loaderName name that you registered the loader under
     */
    
    assign : function(id, loaderName) {
      
      // this will error if loaderName is not registered
      var loader = this.get(loaderName);
      
      // link loader
      this._loaders[id] = loaderName;

    },

    /**
     * get loader linked to data id via __link__
     * @method loader
     * @param {String} id data_id
     * @returns {Object} loader instance of loader
     */

    loader : function(id, config) {
      if(!this._loaders[id])
        throw("Could not find suitable loader for data id "+id+", are you certain it's assigned?");

      var loader = this.get(this._loaders[id]);
      return new loader(id, config || {});
    }

  },
  twentyc.cls.Registry
);
twentyc.data.loaders = new twentyc.data.LoaderRegistry();

/**
 * any new loader you register should at the very least
 * extend this loader
 *
 * @class Base
 * @module twentyc
 * @namespace twentyc.data.loaders.get
 * @constructor
 * @param {String} id data id
 * @param {Object} [config] object literal holding config attributes
 */
twentyc.data.loaders.register(
  "Base",
  {
    Base : function(id, config) {
      this.dataId = id;
      this.config = config || {};
    },
    retrieve : function(data) {
      var set = tc.u.get(data, this.dataId)
      if(typeof set == undefined)
        return {};
      return set;
    },
    load : function() {
      throw("The load() function needs to be overwritten to do something")
    }
  }
);


/**
 * you may use this loader as a base class for any xhr data retrieval
 * loaders you define. during the ctor you will need to set the url
 * attribute on this.config
 *
 * @class XHRGet
 * @module twentyc
 * @namespace twentyc.data.loaders._classes
 * @constructor
 * @param {String} id data id
 * @param {Object} [config] object literal holding config attributes
 * @param {String} [config.url] url of the request
 * @param {Object} [config.data] parameters to send 
 */

twentyc.data.loaders.register(
  "XHRGet",
  {
    load : function(callbacks) {
      var url = tc.u.get(this.config, "url");
      var loader = this;
      if(url == undefined)
        throw("XHRGet loader needs url, "+this._meta.name);
      $.ajax(
        {
          url : url,
          data : this.config.data,
          success : function(data) {
            if(typeof callbacks.success == "function")
              callbacks.success(loader.retrieve(data));
          }
        }
      ).fail(function(response) {
        if(callbacks.error)
          callbacks.error(response);
      });
    }
  },
  "Base"
);

/**
 * Timeout that will reset itself when invoked again before
 * execution
 *
 * @class SmartTimeout
 * @namespace twentyc.util
 * @constructor
 * @param {Function} callback 
 * @param {Number} interval trigger in N ms
 */

twentyc.util.SmartTimeout = twentyc.cls.define(
  "SmartTimeout",
  {
    SmartTimeout : function(callback, interval) {
      this.set(callback, interval);
    },

    /**
     * Reset / start the timeout
     * @method set
     * @param {Function} callback 
     * @param {Number} interval trigger in N ms
     */

    set : function(callback, interval) {
      this.cancel();
      this._timeout = setTimeout(callback, interval);
    },

    /**
     * Cancel timeout
     * @method cancel
     */
    
    cancel : function() {
      if(this._timeout) {
        clearTimeout(this._timeout);
        this._timeout = null;
      }
    }
  }
);

/**
 * jQuery helper functions
 * 
 * @class jq
 * @static
 * @namespace twentyc
 */

twentyc.jq = {
  
  /**
   * define a jquery plugin
   *
   * @method plugin
   * @param {String} name plugin name as it will be used to access the plugin
   * on the jquery resultset
   * @param {Object} definition object literal defining methods of the plugin
   * @param {Object} config object literal with default plugin config
   */
 
  plugin : function(name, definition, config) {
    
    if(!definition.init) {
      throw("Plugin definition for jQuery."+name+" missing init method");
    }

    jQuery.fn[name] = function(arg) {
      
      if(definition[arg]) {
        return definition[arg].apply(this, Array.prototype.slice.call(arguments, 1));
      } else if(typeof arg === "object" || !arg) {
        var opt = jQuery.extend(config || {}, arg);
        return definition.init.call(this, opt);
      } else {
        throw("Method "+arg+" does not exist on jQuery."+name);
      }

    }

  }

}

/**
 * shortcuts
 */

tc = {
  u : twentyc.util,
  def : twentyc.cls.define,
  ext : twentyc.cls.extend
}

})();
