Template.subscribeLayout.onCreated ->
  @selectedPlan = new ReactiveVar(false)
  @animalData = new ReactiveVar(false)

  steps = ['plan', 'dog', 'owner', 'payment']

  @stepCompleted = (name) =>
    switch name
      when 'plan'
        @selectedPlan.get() and 'completed'
      when 'dog'
        (Meteor.user()?.profile.animal? or @animalData.get()) and 'completed'
      when 'owner'    then Meteor.user()?.addressCombined() and 'completed'
      when 'payment'  then false

  @nextStep = => _.find steps, _.negate(@stepCompleted)

Template.subscribeLayout.helpers

  stepTemplate: -> 'subscribe' + _.capitalize FlowRouter.getParam('step')

  ownerStepTitle: -> Meteor.user()?.addressCombined() or "Доставка"

  dogStepSubtitle: ->
    animal = Meteor.user()?.profile.animal or Template.instance().animalData.get()
    if animal then "#{animal.breed} #{animal.name}" else "Собака"

  planStepSubtitle: ->
    plan = Template.instance().selectedPlan.get()
    switch plan
      when "0" then "Одна промокоробка за 1500 рублей"
      when "1" then "Месяц за 2990 рублей"
      when "3" then "3 месяца по 2490 рублей в месяц"
      when "6" then "Полгода по 2190 рублей в месяц"
      when "12" then "Год по 1990 рублей в месяц"
      else "Коробка"

Template.subscribePlan.events

  'click .plan.column': (ev, tpl) ->
    rootTpl = tpl.findParentTemplate('subscribeLayout')
    rootTpl.selectedPlan.set $(ev.currentTarget).attr('data-plan')

    FlowRouter.go 'subscribe', step: rootTpl.nextStep()

Template.subscribePlan.helpers

  planIsSelected: (plan) -> if Template.instance().findParentTemplate('subscribeLayout').selectedPlan.get() == plan then 'selected' else false

Template.subscribeDog.helpers

  animalData: -> Meteor.user()?.profile.animal or Template.instance().findParentTemplate('subscribeLayout').animalData.get()

Template.subscribeStep.helpers

  stepCompleted: -> Template.instance().findParentTemplate('subscribeLayout').stepCompleted @name

  stepDisabled: ->
    return false unless @name == 'payment'
    rootTpl = Template.instance().findParentTemplate('subscribeLayout')
    if _.every(['dog','owner','plan'], (step) -> rootTpl.stepCompleted step) then "" else "disabled"

  stepPath: -> FlowRouter.path 'subscribe', step: @name

Template.subscribeOwner.onRendered ->
  if not Meteor.user()
    @autorun (c) =>
      user = Meteor.user()
      if user
        c.stop()
        @$('#subscribeOwnerForm').submit()

Template.subscribeOwner.helpers

  ownerIsReady: ->
    p = Meteor.user()?.profile
    p and p.firstName and p.lastName and p.phone and p.address?.city and p.address?.street and p.address?.premise

  nextStepPath: -> FlowRouter.path 'subscribe', step: Template.instance().findParentTemplate('subscribeLayout').nextStep()

Template.subscribePayment.events

  'click .paymentCompleteStub': (ev, tpl) ->
    Meteor.user().newSubscription(plan: tpl.findParentTemplate('subscribeLayout').selectedPlan.get())
    FlowRouter.go 'user'

AutoForm.hooks

  subscribeDogForm:
    onSubmit: (doc) ->
      SB.Schemas.Animal.clean(doc)
      rootTpl = Template.instance().findParentTemplate('subscribeLayout')
      rootTpl.animalData.set doc
      Tracker.autorun (c) ->
        if Meteor.user()
          c.stop()
          Meteor.user().update $set: "profile.animal": rootTpl.animalData.get()
      FlowRouter.go 'subscribe', step: rootTpl.nextStep()
      @done()
      false
