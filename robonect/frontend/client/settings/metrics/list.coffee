# Список метрик

Template.metricHeaders.onCreated ->
	tpl = @
	requestValues = ->
		Meteor.call 'metricLastValues', (err, result) ->
			if not err
				Session.set "overview:values", result
				tpl.timer = Meteor.setTimeout requestValues, 10000
	requestValues()

Template.metricHeaders.onDestroyed -> Meteor.clearTimeout @timer

Template.metricItem.helpers
	lastValue: ->
		values = Session.get "overview:values"

		timestamp: if values and @id of values then moment(values[@id].timestamp) else false
		value: if values and @id of values then @formatValue values[@id].value else false

Template.metricItem.events
	'click .metric-link': (ev) ->
		if not @metric? then m = @ else m = @metric
		Session.set "browser:selectedMetrics", [m.id]
		if not (Router.current() instanceof DatabrowserController)
			Router.go 'databrowser'
		ev.preventDefault()
