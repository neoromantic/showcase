# charges:
#   [
#     transactionId:
#     processedAt:
#     cardId:
#     amount:
#     result:
#     log:
#   ]
#

SB.Schemas.SignupForm = new SimpleSchema
  email:
    type: String
    regEx: [SimpleSchema.RegEx.Email, /.+\@.+\.\w{2,9}/]
  password:
    type: String
    min: 6

SB.Schemas.Card = new SimpleSchema
  cardId:
    type: String
  number:
    type: String
  expire:
    type: String
  primary:
    type: Boolean
  valid:
    type: Boolean

SB.Schemas.Animal = new SimpleSchema
  name:
    label: "Имя"
    type: String

  age:
    label: "День рождения"
    type: Date
    optional: true

  breed:
    label: "Порода"
    type: String
    allowedValues: SB.Dictionaries.Breeds
    autoform:
      type: 'select'

  sex:
    label: "Пол"
    type: String
    allowedValues: SB.Dictionaries.DogSexes.keys()
    autoform:
      type: 'select-radio'
      options: SB.Dictionaries.DogSexes.options()

  size:
    label: "Размер"
    type: String
    allowedValues: SB.Dictionaries.DogSizes.keys()
    autoform:
      type: 'select-radio'
      options: SB.Dictionaries.DogSizes.options()

  story:
    label: "Примечания (аллергии, особенности, пожелания)"
    type: String
    optional: true
    max: 4000
    autoform:
      afFieldInput:
        type: 'textarea'
        rows: 3

SB.Schemas.Address = new SimpleSchema

  city:
    type: String
    label: "Город"

  street:
    type: String
    label: "Улица"

  premise:
    type: String
    label: "Дом"

  apartment:
    type: Number
    optional: true
    label: "Квартира"

  description:
    type: String
    label: "Комментарии для курьера"
    max: 4000
    optional: true
    autoform:
      afFieldInput:
        type: 'textarea'
        rows: 3

SB.Schemas.Subscription = new SimpleSchema

  id:
    type: String

  plan:
    type: Number

  monthsLeft:
    type: Number

  payed:
    type: Boolean
    optional: true

  payedOn:
    type: Date

  # Здесь же — всякие параметры от яндекса — типа номер карты и транзакции и т.п

SB.Schemas.UserProfile = new SimpleSchema
  firstName:
    type: String
    label: "Имя"
    optional: true
  lastName:
    type: String
    label: "Фамилия"
    optional: true
  # middleName:
  #   type: String
  #   label: "Отчество"
  #   optional: true
  phone:
    type: String
    label: "Мобильный телефон"
    optional: true

  animal:
    type: SB.Schemas.Animal
    optional: true

  address:
    type: SB.Schemas.Address
    optional: true

  cards:
    type: [SB.Schemas.Card]
    optional: true

class SB.Users extends Model

  @schema: new SimpleSchema
    emails:
      type: [Object]
      optional: true

    registered_emails: { type: [Object], blackbox: true, optional: true }

    "emails.$.address":
      type: String,
      regEx: SimpleSchema.RegEx.Email

    "emails.$.verified":
      type: Boolean

    createdAt:
      type: Date

    profile:
      type: SB.Schemas.UserProfile
      optional: true

    subscriptions:
      type: [SB.Schemas.Subscription]
      optional: true

    services:
      type: Object
      optional: true
      blackbox: true

  # # Публичная информация о пользователях с данными id
  # @publicUsers: (ids) ->
  #   SK.Users.find {_id: $in: ids},
  #     fields:
  #       '_id': true
  #       'profile': true
  #

  # Общепользовательские свойства
  isLogged: -> @_id == Meteor.userId()
  # avatarUrl: (size) ->
  #   if @profile.userpic then $.cloudinary.url(@profile.userpic, {width: size, height: size, crop: 'fill', gravity: 'faces'}) else "/userpic/#{_.random(1,6)}.jpg"

  prettyJSON: ->
    EJSON.stringify _.omit(@, ['services'] ), {indent: true, canonical: true}

  addRandomCard: ->
    newCardId = Random.id()
    cards = @profile.cards or []

    cards.push
      cardId: newCardId
      number: _.padLeft _.random(0,9999), 4, '0'
      expire: _.padLeft(_.random(12), 2, '0') + '/' + _.random(15,19)
      primary: true
      valid: true

    @update $set: "profile.cards": cards

    @setPrimaryCard newCardId

  removeCard: (cardId) ->
    @update $pull: "profile.cards": cardId: cardId, {}, ->
      user = Meteor.user()
      if not _.find(user.profile.cards, 'primary') and user.profile.cards.length
        user.setPrimaryCard user.profile.cards[0].cardId

  setPrimaryCard: (cardId) ->
    cards = @profile.cards
    for card in cards
      card.primary = card.cardId == cardId
    @update $set: "profile.cards": cards

  name: ->
    return false unless @profile.firstName and @profile.lastName
    "#{@profile.firstName} #{@profile.lastName}"

  addressCombined: ->
    return false unless @profile.address
    _.values(_.pick(@profile.address, _.identity)).join(', ')

  email: -> @registered_emails?[0].address

  newSubscription: (options) ->
    subscription =
      plan: parseInt(options.plan)
      monthsLeft: parseInt(options.plan)
      payed: true
      id: Random.id()
      payedOn: new Date()

    @update $push: "subscriptions": subscription

  activeSubscription: ->
    return false unless @subscriptions
    for subscription in @subscriptions
      return subscription if subscription.payed and subscription.monthsLeft > 0

SB.Users.init
  collection: Meteor.users

  allow:
    # insert: (userId) -> userId?
    update: (userId, doc, fields, modifier) -> doc._id == userId
    # remove: (userId, doc) -> doc.owner_id == userId
    fetch: ['_id']

if Meteor.isServer

  Accounts.onCreateUser (options, user) ->

    user.profile = _.extend {}, options.profile or {}

    if user.services.facebook?
      user.profile = _.extend user.profile,
        firstName: user.services?.facebook?.first_name
        lastName: user.services?.facebook?.last_name
        gender: user.services?.facebook?.gender

    user
