FlowRouter.route '/',
  action: ->
    if Meteor.settings.public.hideWeb
      BlazeLayout.render "emptyLayout", content: "stubPage"
    else
      BlazeLayout.render "mainLayout", content: "homePage"

FlowRouter.route '/subscribe/:step',
  name: 'subscribe'
  action: ->
    BlazeLayout.render "noFooterLayout",
      content: 'subscribeLayout'

FlowRouter.route '/tour',
  name: 'tour'
  action: -> BlazeLayout.render "mainLayout", content: "tourPage"


FlowRouter.route '/user',
  name: 'user'
  action: -> BlazeLayout.render "mainLayout", content: "userHomePage"

FlowRouter.route '/login',
  action: -> BlazeLayout.render "mainLayout",
    content: "loginPage"
    redirectAfterLogin: true

FlowRouter.route '/logout',
  triggersEnter: [(context, redirect) ->
    Meteor.logout()
    redirect('/')
  ]
