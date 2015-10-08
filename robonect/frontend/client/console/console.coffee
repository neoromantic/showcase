Template.init 'console',
	onCreated: ->
		# Определение state консоли
		@state =
			chosenPort: new ReactiveVar(false)
			lockedPort: new ReactiveVar(false)

			# Включает или выключает запись в фрейм консоли
			switchInput: (isEnabled) ->
				$('.consoleFrame')[0].contentWindow.postMessage (if isEnabled then "un" else "") + "lock", "*"

			# Вызванный без параметров — разблокирует ранее заблокированный порт.
			# С параметром — заблокирует указанный
			switchLock: (portId) ->
				isLocked = portId and portId != @lockedPort.get()
				portId = portId or @lockedPort.get()
				if portId
					Meteor.apply (unless isLocked then "un" else "") + 'lockPort', [portId], onResultReceived: (err, res) =>
						port = Models.Connection.findOne(portId)
						if not err and res.result.result
							@lockedPort.set isLocked and portId
							@switchInput isLocked

							Output.post "Вы " + (if isLocked then "заблокировали" else "разблокировали") + " порт #{port.title}", {quiet: true}
						else
							Output.post 'Не удалось ' + (if isLocked then "заблокировать" else "разблокировать") + ' порт', {type: 'danger'}

			extendLock: ->
				lockedPortId = @lockedPort.get()
				Meteor.call('extendLock', lockedPortId) if lockedPortId

			chosePort: (portId) ->
				# Разблокировать ранее заблокированный порт
				@switchLock()
				@chosenPort.set(portId)

		@_extendTimerId = Meteor.setInterval =>
			@state.extendLock()
		, 30000

	onDestroyed: ->
		@state.switchLock()
		Meteor.clearInterval @_extendTimerId

	helpers:
		portOptions: ->
			options = {}
			for obj in _.filter(Models.Connection.all(), (connection) -> connection.consoleAllowed() and not connection.flags.noselect)
				options[obj.id] = obj.title
			options

		lockedPort: -> Template.instance().state.lockedPort.get()
		chosenPort: -> Template.instance().state.chosenPort.get()

	events:
		'change [name="COMPort"]':
			(ev, tpl) -> tpl.state.chosePort $(ev.currentTarget).val()
		'click .releaseLockButton':
			(ev, tpl) -> tpl.state.switchLock()
		'click .getLockButton':
			(ev, tpl) -> tpl.state.switchLock tpl.state.chosenPort.get()

Template.init 'iframeConsole',
	helpers:
		adjustedPortId: -> Template.instance().parentTemplate().state.chosenPort.get().replace(/\:/g,"_")

	onRendered: ->
		# Заблокировать ввод сразу как загрузилось окно
		parent = @parentTemplate()
		$('.consoleFrame').on 'load', -> Meteor.defer -> parent.state.switchInput()

		# Подстраивать высоту консоли под окно браузера
		$(window).on('resize', => $('.consoleFrame').height $(window).innerHeight() - $('.consoleFrame').offset().top - 20).trigger('resize')
