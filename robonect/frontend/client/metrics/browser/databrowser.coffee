Template.databrowser.onCreated ->
	tpl = @

	tpl.selectedMetrics = new ReactiveVar([])
	tpl.options = new ReactiveVar({})

	tpl.widget = Models.Widget.create
		axes: true
		_id: "robonect:widget:" + Random.id()

	@autorun ->
		params = Router.current().getParams().query
		selectedMetrics = _.compact(params.selectedMetrics?.split(",") or [])

		tpl.options.set _.extend
			type: 'graph.area-spline'
			resolution: '1m'
			limit: 20
			date_from: false
			date_to: false
		, _.omit(params, 'selectedMetrics')
		tpl.selectedMetrics.set selectedMetrics

	# Настройки параметров виджета
	tpl.autorun (c) ->
		options = tpl.options.get()
		selectedMetrics = tpl.selectedMetrics.get()

		Router.go 'databrowser', {}, query:
			_.extend options,
				date_from: options.date_from or ''
				date_to: options.date_to or ''
				selectedMetrics: selectedMetrics.join ","

		_.extend tpl.widget, options
		tpl.widget.metric_ids = selectedMetrics
		tpl.widget._changed()


	# Следим, выбрана ли хоть одна метрика годная для графика
	tpl.digitalMetricSelected = new ReactiveVar(false)
	tpl.autorun ->
		tpl.digitalMetricSelected.set _.any tpl.selectedMetrics.get(), (mid) ->
			metric = Models.Metric.findOne(mid)
			metric and metric.graphable()

	# Если не осталось цифровых метрик, а отображается график, то надо переключиться на таблицу
	tpl.autorun ->
		options = tpl.options.get()
		digitalMetrics = tpl.digitalMetricSelected.get()

		if not digitalMetrics and options.type == 'graph'
			options.type = 'table'
			tpl.options.set options

Template.databrowser.events

	# Выбрали или наоборот метрику
	'click .metricList .item': (ev, tpl) ->
		current = tpl.selectedMetrics.get()
		tpl.selectedMetrics.set if @id in current then _.without current, @id else _.union current, [@id]

	# Сброс выбранных метрик
	'click .clearMetrics': ->
		Template.instance().selectedMetrics.set []

	'change .metricOptions [name="type"]': (ev, tpl) ->
		options = tpl.options.get()
		if ev.currentTarget.value != 'digest' and parseInt(options.limit) == 1
			$('.metricOptions [data-value="20"]').click()

	'change .metricOptions [name="limit"]': (ev, tpl) ->
		options = tpl.options.get()
		if parseInt(ev.currentTarget.value) == 1 and options.type != 'digest'
			$('.metricOptions [data-value="digest"]').click()

	'change .metricOptions [name]': (ev, tpl) ->
		current = tpl.options.get()
		current[@name] = $(ev.currentTarget).val()
		tpl.options.set current

	# Сохранение данных в CSV
	'click .btn-save-to-csv': (ev, tpl) ->
		data = tpl.widget.formattedData()
		sep  = ';'
		csv = "Date/time" + sep + (metric.title for metric in data.metrics).join(sep) + "\n"
		_.each data.rows, (row) ->
			csv += row.time + sep + (point.formattedValue for point in row.values).join(sep) + "\n"
		blob = new Blob([csv], {type: "text/csv"})
		saveAs(blob, "robonect.csv")

	# Добавление виджета в сводку
	'click .btn-add-to-dashboard': (ev, tpl) ->
		tpl.widget.axes = false
		tpl.widget.height = 6
		tpl.widget.width = 8
		tpl.widget.title = Models.Metric.findOne(tpl.widget.metric_ids[0]).title# + if mc > 0 then ' (и еще ' + mc + ' метрик' + (if mc == 1 then 'а' else if mc < 5 then 'и' else '') + ')' else ''

		tpl.widget.save()
		Router.go 'dashboard'

Template.databrowser.helpers
	widget: ->
		Template.instance().widget._dep.depend()
		Template.instance().widget

	metrics: ->
		selected = Template.instance().selectedMetrics.get()
		searchFilter = Template.instance().searchFilter.get()
		res =_.groupBy _.map(Models.Metric.all(), (metric) ->
				metric.active = if  metric.id in selected then 'selected' else 'others'
				metric.hidden = searchFilter and metric.title.toLowerCase().indexOf(searchFilter) == -1
				metric
		), (metric) -> metric.active
		res

	options: -> Template.instance().options.get()

	typeOptions:
		table: 'Таблица'
		graph:
			title: 'График'
			sub:
				line: 'Ломаная',
				spline: 'Гладкая',
				bar: 'Столбики',
				'bar.stacked': 'Столбики группой',
				step: 'Лесенка',
				area: 'Площадь',
				'area.stacked': 'Площадь группой',
				'area-spline': 'Гладкая площадь',
				'area-spline.stacked': 'Гладкая площадь групп.',
				'area-step': 'Площадь лесенкой'
				'area-step.stacked': 'Площадь лесенкой групп.'
		digest: 'Дайджест'

	typeEqual: (type) -> type == Template.instance().options.get().type

	resolutionOptions:
		# '1s': 'Секунда'
		'1m': 'Минута'
		'1h': 'Час'
		'1d': 'День'
		'1w': 'Неделя'
		'raw': 'Без агрегации'
	resolutionEqual: (option) -> option == Template.instance().options.get().resolution

	limitOptions: ->
		result = {}
		for i in [1,3,5,10,20,50,100,500,5000]
			result[i] = i
		result

	hasDigitalMetrics: -> Template.instance().digitalMetricSelected.get()
