regexpValid = (str) ->
	try
		new RegExp(str)
		return true
	catch err
		return false

Template.metricEditForm.onCreated ->
	@actionActive = new ReactiveVar(false)
	@dataSource = new ReactiveVar(if @data.editDoc.connection then "connection" else "action")
	@actionResult = new ReactiveVar(false)

Template.metricEditForm.onRendered ->
	@$('.ui.checkbox').checkbox()

	Session.set "metric:justRendered", true

	Meteor.setTimeout ->
		Session.set "metric:justRendered", false
	, 500

	field = @$('[name="unit"]').closest('.dropdown')
	options =
		fullTextSearch: true
		forceSelection: false
		onNoResults: (searchValue) ->
			$('[name="unit"]').val(searchValue).change()
		onShow: ->
			Meteor.setTimeout =>
				el = $(@).find('.menu')
				offset = el.offset().top + el.height() - $('.pageContent').innerHeight()
				if offset > 0
					$('.pageContent').scrollTo($('.pageContent').scrollTop() + offset * 1.05, duration: 500)
			, 500

	tpl = @

	Meteor.setTimeout ->
		field.dropdown options
		if tpl.data.editDoc.unit not in _.keys tpl.data.editDoc.fields().unit.options
			field.dropdown 'set text', tpl.data.editDoc.unit
	, 0


Template.metricEditForm.helpers
	dataSourceIsAction: -> Template.instance().dataSource.get() == "action"
	actionActive: -> Template.instance().actionActive.get()
	actionResult: -> Template.instance().actionResult.get()

Template.metricEditForm.events

	# При изменении действия, нужно сбросить selectedLines у метрики и значение результата выполнения действия
	'change [name="action"]': (ev, tpl) ->
		unless Session.get "metric:justRendered"
			tpl.data.editDoc.resetSelection()
			tpl.actionResult.set false

	# Если изменился тип метрики, то агрегации надо сбросить на дефолтную
	'change [name="type"]': (ev, tpl) ->
		unless Session.get "metric:justRendered"
			tpl.data.editDoc.aggregate = undefined

	'change input[name="dataSource"]': (ev, tpl) ->
		unless Session.get "metric:justRendered"
			newDS = $(ev.target).val()
			tpl.dataSource.set newDS
			tpl.actionResult.set false
			tpl.data.editDoc.resetSelection()
			tpl.data.editDoc[if newDS == "action" then "connection" else "action"] = false

	# Клик на номер строки — включаем или выключаем ее в объекте метрики
	'click .line-number': (ev, tpl) ->
		lines = tpl.data.editDoc.selectedLines()
		if @index in lines then lines.splice lines.indexOf(@index), 1 else lines.push @index
		tpl.data.editDoc.resetSelection()
		tpl.data.editDoc.selectedLines(lines)

	# Валидируем поле regexp на лету, для удобства ввода
	'input input[name="line_regexp"]': (ev) ->
		regexp = $(ev.target).val()
		$(ev.target).closest('.form-group').toggleClass 'has-error', regexp.length>0 and not regexpValid(regexp)

	'mouseover .line-text-word, mouseover .line-text-whitespace': (ev, tpl) ->
		$('.line-text-word.hovered, .line-text-whitespace.hovered').removeClass('hovered')

		current = tpl.data.editDoc.selectedWords()

		if current.finish == current.start
			$('.line-text-word.selected ~ .line-text-word:hover').prevUntil('.line-text-word.selected').addClass('hovered')
		else
			$(ev.target).filter('.line-text-word').addClass('hovered')

	'click .line-text-word': (ev, tpl) ->
		doc = tpl.data.editDoc
		if doc.selectedWords().start and @lindex not in doc.selectedLines()
			doc.selectedWords []
		current = doc.selectedWords()
		doc.selectedLines [@lindex]
		if current.start
			if current.start != current.finish
				doc.selectedWords {start: @index}
			else
				if @index < current.start
					doc.selectedWords {start: @index}
				else if @index > current.start
					doc.selectedWords {start: current.start, finish: @index}
				else
					doc.resetSelection()
		else
			doc.selectedWords {start: @index}

Template.metricEditForm.helpers
	matchedText: ->
		regexp = @editDoc.word_regexp or ""
		if regexp.length>0 and (not regexpValid(regexp) or not regexp.match "[\(].*[\)]")
			$('input[name="word_regexp"]').closest('.form-group').addClass 'has-error'
			return TAPi18n.__("settings_metrics_regexp_error")
		else
			$('input[name="word_regexp"]').closest('.form-group').removeClass 'has-error'

		if not @editDoc.word_regexp
			return ""
		else
			actionResult = Template.instance().actionResult.get()
			if actionResult and not actionResult.error
				activeLines = _.map $('.action-result-line:has(.line-number.matched), .action-result-line:has(.line-number.selected)'), (el) -> $(el).index()
				text = actionResult.message
				if activeLines.length
					text = _.filter(text.split('\n'), (line, index) -> index in activeLines).join("\n")
				match = text.match(regexp)
				return if match then TAPi18n.__("settings_metrics_value_found") + match[1] else TAPi18n.__("settings_metrics_value_not_found") + if activeLines.length then TAPi18n.__("settings_metrics_probably_line") else ""
			return ""

	wordIsSelected:  (line_index) ->
		line_index in @editDoc.selectedLines() and @index <= @editDoc.selectedWords().finish and @index >= @editDoc.selectedWords().start

	lineIsSelected: ->
		@editDoc and @index in @editDoc.selectedLines()

	lineIsMatched: ->
		@editDoc and not @editDoc.selectedWords().start and @editDoc.matchLine(_.pluck(@line, 'word').join(""))

	disabledRegexp: ->
		@editDoc.selectedWords().start

	# Генерируем массив строк и слов в них из текста, полученного от выполнения действия
	# Если действие еще на запускалось, запускаем его.

	actionText: ->
		tpl = Template.instance()

		wordSplitRegexp = /( +|\t+|\(|\)|\.|\:|\=|,|\%|\/|\\|\[|\]|;|\"|\')|(-(?!\d))/
		negativeDigitsRegexp = /(.+)(-)/
		wordWhitespaceRegexp = /^[ \t]+$/

		actionResult = Template.instance().actionResult.get()
		dataSource = Template.instance().dataSource.get()

		if dataSource != "action"
			return ""

		if actionResult.error
			return actionResult

		result = false

		if not actionResult
			# Если еще не запускали action, то нужно запустить его и ждать ответа
			if @editDoc and @editDoc.action and tpl.actionActive.get() != @editDoc.action.id
				tpl.actionActive.set @editDoc.action.id
				# Session.set "metricActionResult", {error: false, message: "some shitty text-shit - value is -54"}
				@editDoc.action.execute {}, (err, result) ->
					tpl.actionResult.set if err then {error: true, message: err.message} else {error: false, message: result.stdout}
					tpl.actionActive.set false

		else
			result = _.extend {}, actionResult
			result.message = if actionResult.message then actionResult.message.split("\n") else []

			result.message = _.map result.message, (item, index) ->
				words = _.compact item.split(wordSplitRegexp)
				words = _.compact _.reduce words, (memo, word) ->
					memo = memo.concat word.split(negativeDigitsRegexp)
				, []
				lindex = index
				skipindex = 0
				line: _.map words, (word, index) ->
					if word.match wordWhitespaceRegexp
						skipindex +=1
						windex = false
					else
						windex = index+1-skipindex

					word: word
					index: windex
					lindex: lindex+1

				index: index+1
		result


	connectionOptions: ->
		options = {}
		for obj in _.filter(Models.Connection.all(), (connection) -> connection.isCOMPort() and not connection.flags.noselect)
			options[obj.id] = obj.title
		options
