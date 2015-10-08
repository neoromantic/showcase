########################################################################################################################
#
#   Модель Триггеров и всего с ними связанного
#
########################################################################################################################

# Условие у триггера (также используется в булевых метриках)

class @Condition extends RobonectModel

	@fields:
		function:
			required: true
		value:
			required:
				dependsOn: "function"
				valueNot: ["isTrue", "isFalse"]

	@relates_to:
		metric:
			model: "Models.Metric"
			required: true

	typeOptions: ->
		allOptions =
			'isTrue': 'Правда'
			'isFalse': 'Ложь'
			'exact': 'в точности равно'
			'contains': 'включает строку'
			'ncontains': 'не включает строку'
			'gt': 'больше'
			'gte': 'больше или равно'
			'lt': 'меньше'
			'lte': 'меньше или равно'
			'eq': 'в точности равно'
			'neq': 'не равно'

		options = _.pick allOptions, switch @metric.type
			when 'boolean' then ['isTrue', 'isFalse']
			when 'string' then ['exact', 'contains', 'ncontains']
			when 'integer', 'float'	then ['gt','gte','lt','lte','eq','neq']

		if not @function of options then options[@function] = allOptions[@function]

		options

	functionAsText: ->
		@typeOptions()[@function]

class Models.Trigger extends RedisModel

	@_namespace: "trigger"

	@has_many:
		scenario:
			model: "ActionCall"
			required: true
			messageRequired: "Нужно хотя бы одно действие"

		conditions:
			model: Condition
			required: true
			messageRequired: "Нужно хотя бы одно условие"

	@fields:
		title:
			required: true
			unique: true
		description: true
		tags: true

	@titles:
		singular: "Триггер"
		plural: "Триггеры"
		genitive: "Триггера"
		accusative: "Триггер"
		dative_plural: "Триггерам"

	updateScenarioParams: (action_index) ->
		action = Models.Action.findOne @_attr.scenario[action_index].action_id, nocache: true
		@_attr.scenario[action_index].params = action._attr.params
		@_changed()
