Template.userCardList.helpers

  canBecomePrimary: -> Meteor.user().profile.cards.length > 1 and not @primary

Template.userCardList.events

  'click .addCard': ->
    Meteor.user().addRandomCard()

  'click .removeCard': ->
    if confirm("Вы уверены?")
      Meteor.user().removeCard @cardId

  'click .makeCardPrimary': -> Meteor.user().setPrimaryCard(@cardId)

Template.userHomePage.events

  'click .editProfile': (ev, tpl) ->
    tpl.$('.profileSummary').hide()
    tpl.$('.editProfileForm').show()

  'click .cancelSubscription': ->

  'click .editBoxOptions': -> $('.boxOptions').transition('slide down')

Template.userHomePage.helpers

  profileIsntComplete: ->
    lackInfo = []
    lackInfo.push "е имя" if not Meteor.user().name()
    lackInfo.push " телефон" if not Meteor.user().profile.phone
    lackInfo.push " адрес доставки" if not Meteor.user().addressCombined()

    switch lackInfo.length
      when 1 then lackInfo[0]
      when 2 then lackInfo.join(" и ")
      when 3 then "#{lackInfo[0]},#{lackInfo[1]} и#{lackInfo[2]}"
      else false

# AutoForm.hooks
  # editDogForm:
    # onSuccess: -> $('.boxOptions').transition('slide down')
