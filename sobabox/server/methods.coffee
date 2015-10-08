Meteor.methods

  emailIsKnown: (email) ->
    check(email, String)
    if Meteor.users.findOne({"registered_emails.address": email}) then true else false
