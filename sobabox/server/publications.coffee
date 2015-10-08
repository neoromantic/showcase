Meteor.publish "currentUser", ->
  if @userId
    Meteor.users.find {_id: @userId},
      fields:
        'registered_emails': true
        'profile': true
        'subscriptions': true
  else
    @ready()
