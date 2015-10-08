Template.login.onCreated ->
  @emailIsValid = new ReactiveVar(false)
  @emailIsKnown = new ReactiveVar(false)
  @passwordIsValid = new ReactiveVar(false)

Template.login.onRendered ->
  @autorun =>
    unless @emailIsValid.get()
      @emailIsKnown.set false

Template.login.helpers

  emailIsValid: -> Template.instance().emailIsValid.get()
  emailIsKnown: -> Template.instance().emailIsKnown.get()
  validNewUser: ->
    tpl = Template.instance()
    tpl.emailIsValid.get() and not tpl.emailIsKnown.get() and tpl.passwordIsValid.get()

Template.login.events

  'click .loginWithFacebook': ->
    Meteor.loginWithFacebook (err) =>
      if not err and @redirectAfterLogin
        FlowRouter.go 'user'

  'keyup [name="email"]': _.debounce (ev, tpl) ->
    email = $(ev.currentTarget).val()
    emailValid = SB.Schemas.SignupForm.newContext().validateOne email: email, 'email'
    tpl.emailIsValid.set emailValid
    if emailValid
      Meteor.call 'emailIsKnown', email, (err, res) =>
        tpl.emailIsKnown.set not err and res
  , 200

  'keyup [name="password"]': _.debounce (ev, tpl) ->
    pwd = tpl.$('[name="password"]').val()
    email = tpl.$('[name="email"]').val()
    if tpl.emailIsKnown.get()
      Meteor.loginWithPassword email, pwd, (err) =>
        if not err and @redirectAfterLogin
          FlowRouter.go 'user'
    else
      tpl.passwordIsValid.set SB.Schemas.SignupForm.newContext().validateOne password: pwd, 'password'
  , 200

  'submit .signupForm': (ev, tpl) ->
    ev.preventDefault()
    pwd = tpl.$('[name="password"]').val()
    email = tpl.$('[name="email"]').val()
    Accounts.createUser
      email: email
      password: pwd
    , (err) =>
      if not err and @redirectAfterLogin
        FlowRouter.go 'user'
      # Meteor.user().update $set: "profile.animal": tpl.findParentTemplate('subscribeLayout').animalData.get()
      # Meteor.defer => tpl.$('#subscribeOwnerForm').submit()
