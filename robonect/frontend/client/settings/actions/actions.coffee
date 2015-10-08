Template.actionItem.helpers
	paramsJoined: -> _.pluck(@params, 'param').join ', '

Template.actionItem.events
	'click .btn-run-action': (ev, tpl) ->
		ev.stopPropagation()

		Output.post "Вы запустили действие '#{@title}'"

		tpl.data.execute {}, (err, result) ->
			if err
				Output.post "Ошибка исполнения действия: " + err.message, {type: 'error'}
			else
				Output.post "Действие завершилось.\n", type: 'success'
				Output.post result.stdout, type: 'longmessage'

		false


Template.scenarioList.onRendered ->
	@$('.popupButton').popup
		inline: false
		delay:
			hide: 300
		hoverable: true
		position: "left center"
		context: '.relativeContainer'

Template.scenarioList.helpers
	displayScenario: ->
		_.map @scenario, (actioncall) ->
			exec: actioncall.action.id == 'robonect:action:exec'
			actioncall: actioncall

Template.scenarioForm.helpers
	actionParamTitleName: ->
		"scenario."+@parentIndex+".params.$.param"

	actionParamValueName: ->
		"scenario."+@parentIndex+".params.$.value"

Template.scenarioForm.onRendered ->
	doc = Template.parentData(4).editDoc

	Session.set "scenario:justRendered", true

	Meteor.setTimeout ->
		Session.set "scenario:justRendered", false
	, 500

	$('.scenario .array-container').sortable
		containerSelector: '.array-container'
		itemPath: '>tbody'
		itemSelector: '.array-item'
		handle: '.itemIndex'
		placeholder: '<tr class="placeholder"><td><div class="ui header"><i class="angle right icon"></i>Переместить сюда</div></td><td></td></tr>'
		onDrop: (item, container, _super, event) ->
			$(item[0]).closest('.array-container').find('.array-item').each (index,item) ->
				old_index = parseInt($(item).attr('data-position'))
				if index != old_index
					doc.scenario.move old_index, index
					return false

			_super(item,container)

Template.actionEditForm.events
	'change [name*="action"]': (ev, tpl) ->
		unless Session.get "scenario:justRendered"
			action_index = @index
			Meteor.setTimeout ->
				tpl.data.editDoc.updateScenarioParams action_index
			, 100
