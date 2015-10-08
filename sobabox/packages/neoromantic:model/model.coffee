class @Model

  # todo: if doc has property like 'filter' or 'find', i.e. one that conflicts with model methods we should do something
  constructor: (doc) -> @transform(doc)

  transform: (doc) -> _.extend @, doc

  @all: (options) ->
    @where({}, options).find()

  @create: (doc) ->
    @collection._transform(doc)

  isNew: -> not @_id?

  collection: ->
    @constructor.collection

  remove: ->
    if @collection().softRemove
      @collection().softRemove @_id
    else
      @collection().remove @_id

  update: (modifier, options, callback) ->
    @collection().update @_id, modifier, options, callback

  save: (onComplete) ->
    if @isNew()
      @collection().insert @, onComplete
    else
      @collection().update @_id, @

  # todo: should combine same ids AND for same ids
  @where: (selector, options) ->
    model: @model or @
    selector: _.extend({}, @selector, selector)
    options: options
    find: -> @model.find(@selector, @options)
    findOne: -> @model.findOne(@selector, @options)
    where: @where

  @find: (selector, options) ->
    @collection.find(selector or {}, options or {})

  @findByIds: (ids) ->
    @find _id: $in: ids

  @findOne: (selector, options) ->
    @collection.findOne(selector or {}, options or {})

  @init: (options = {}) ->
    self = @
    @collection = options.collection or new Meteor.Collection(@name.toLowerCase())
    @collection._transform = (doc) -> new self(doc)
    if options.schema or @schema
      @collection.attachSchema options.schema or @schema

    for ruleset in ["allow", "deny"]
      @collection[ruleset](options[ruleset]) if options[ruleset]
