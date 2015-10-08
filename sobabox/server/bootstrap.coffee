Meteor.startup ->
  if Meteor.users.find().count() == 0
    Accounts.createUser
      email: 'testuser@test.com'
      password: 'testpassword'
      profile:
        firstName: "Test"
        lastName: "User"
