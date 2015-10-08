Template.yandex.helpers

  price: -> FlowRouter.getQueryParam("amount")

Template.yandex.events

  'click .addCard': (ev, tpl) ->

    card =
      cardId: Random.id()
      number: tpl.$('[name="number"]').val()
      cvv: tpl.$('[name="cvv"]').val()
      expire: tpl.$('[name="expire"]').val()
      valid: true
      primary: not Meteor.user().profile.cards?.length
    console.log card
    Meteor.user().update {"$push": {cards: card}}
    FlowRouter.go '/user'
