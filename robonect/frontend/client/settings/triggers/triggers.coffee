Template.triggerEditForm.events

	'change [name*="action"]': (ev, tpl) ->
		action_index = @index
		Meteor.setTimeout ->
			tpl.data.editDoc.updateScenarioParams action_index
		, 100
