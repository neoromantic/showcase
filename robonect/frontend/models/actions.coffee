########################################################################################################################
#
#   Модели Действий и всего с ними связанного
#
########################################################################################################################

# Параметр действия
class @Param extends RobonectModel

	@fields:
		param:
			required: true
		value: true

	@titles:
		singular: "Параметр"
		plural: "Параметры"

# Элемент сценария (Действие и значения для его параметров)
class @ActionCall extends RobonectModel

	@relates_to:
		action:
			model: "Models.Action"

	@has_many:
		params:
			model: Param

	validate: ->
		errors = {}
		index = 0
		for p in @params
			if not p.value
				errors['params.'+index+'.value'] = "Параметр должен быть указан"
			index = index + 1
		_.extend errors, super()

# Действие (Action)
class Models.Action extends  RedisModel

	@_namespace: "action"

	@fields:
		title:
			required: true
			unique: true
		tags: true
		description: true
		schedule:
			format: /^\d+[s|m|h|d]/i
			message: "Расписание указывается в формате %d[s|m|h|d]"
		ttl:
			required: true
			default: 30
			format: "integer"
			message: "Таймаут в секундах"
		utility:
			default: false
			format: "boolean"
		execution_limit:
			format: "integer"
			message: "Время в секундах"

	@has_many:
		params:
			model: "Param"

		scenario:
			model: "ActionCall"
			required:
				dependsOn: "id"
				valueNot: "exec"

	@relates_to:
		connection:
			model: "Models.Connection"

	@titles:
		singular: "Действие"
		plural: "Действия"
		genitive: "Действия"
		accusative: "Действие"
		dative_plural: "Действиям"

	@before_save: (doc) ->
		doc = super doc
		if doc.schedule
			doc.schedule = doc.schedule.replace(" ", '')
		doc

	# Обновляет параметры в сценарии, необходимо в процессе редактирования действия
	updateScenarioParams: (action_index) ->
		action = Models.Action.findOne @_attr.scenario[action_index].action_id, nocache: true
		@_attr.scenario[action_index].params = action._attr.params
		@_changed()

	hasScenario: ->
		@scenario.length

	hasParams: ->
		@params.length

	# Возвращает действия, непосредственно зависящие от данного
	dependents: ->
		self_id = @id
		_.filter Models.Action.all().concat(Models.Trigger.all()), (actionOrTrigger) ->
			_.any actionOrTrigger.scenario, (actioncall) ->
				actioncall.action.id == self_id

	# Проверяет что в сценарии указаны все параметры всех шагов
	scenarioIsCompleted: ->
		_.every @scenario, (actionCall) ->
			_.every actionCall.params, (param) ->
				param.value? and param.value != ''

	# Проверяет, можно ли это действие запустить
	canExecute: (params) ->
		if _.isObject(params) and (_.any(_.keys(params), (key) -> params[key].length == 0) or _.difference(_.map(@params, (param) -> param.param), _.keys(params)).length > 0)
			return false

		@hasScenario() and @scenarioIsCompleted() and (not @hasParams() or params)

	# Запускает действие и возвращает результат в коллбек
	execute: (params, callback) ->
		if _.isFunction params
			callback = params
			params = {}

		action = _.extend {}, @_attr

		Meteor.apply 'runAction', [action, params],
			onResultReceived: (err, result) ->
				if err
					callback err, false
				else
					callback false, result.result
