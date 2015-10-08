Meteor.startup ->

  ServiceConfiguration.configurations.remove {$or: [{service: "facebook"}, {service: "vk"}]}

  ServiceConfiguration.configurations.insert _.extend(service: "facebook", Meteor.settings.oauth.facebook)

  AccountsMeld.configure({})
  # 
  # Accounts.onCreateUser (options, user) ->
  #   if options.profile
  #     user.profile = options.profile
  #   Accounts.sendVerificationEmail user._id
  #   user

 # ServiceConfiguration.configurations.insert
  #   service: "vk",
  #   appId: 4611042
  #   requestPermissions: ['email']
  #   secret: "xLKFpHfkfYOX3mndfk8H"
