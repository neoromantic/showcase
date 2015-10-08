########################################################################################################################
#
#   Интерфейс доступа в базу данных InfluxDB. Умеет делать выборки (select), вставки (insert) и слежение за новыми
#   данными (observe). Потенциальный источник утечек памяти, надо аккуратно.
#
#   Все запросы к Influx происходят по HTTP.
#
########################################################################################################################

@influxDb =

  dbURL: (db) -> "http://#{Meteor.settings.influx.server}:#{Meteor.settings.influx.port}/db/#{db}/series"

  defaultParams:
    u: Meteor.settings.influx.user
    p: Meteor.settings.influx.password
    time_precision: "ms"

  # Такой формат времени требуется для правильных запросов к Influx
  timeFormat: (time) -> time.utc().format("YYYY-MM-DD HH:mm:ss.SSS")

  queryString: (queryObject) ->
    check queryObject, Match.ObjectIncluding
      series: String

    query = _.defaults queryObject,
      columns: ["*"]
      where: []
      group: false
      limit: 500
      fill: false

    # использовалось в objectlog: query.where = query.where() if _.isFunction query.where

    'SELECT ' + query.columns.join(',') +
    " FROM \"#{query.series}\"" +
    (if query.group then " GROUP BY #{query.group}" + (if query.fill then " fill(#{query.fill})" else "") else "") +
    (if query.where.length then (" WHERE " + ("#{c.field} #{c.function} #{c.value}" for c in query.where).join(" AND ")) else "") +
    " LIMIT #{query.limit}"

  select: (db, queryObject, callback) ->
    check db, String

    # Заглушка для дев-режима
    if Meteor.settings.public.stub_metrics and queryObject.fakeData
      callback null, if _.isFunction queryObject.fakeData then queryObject.fakeData() else queryObject.fakeData
    # Настоящий запрос за данными
    else
      try
        result = HTTP.get @dbURL(db),
          timeout: Meteor.settings.influx.timeout
          params: _.extend {}, {q: @queryString queryObject}, @defaultParams
        , callback

      catch err
        throw new Meteor.Error "influx-error", "Ошибка запроса к базе данных", err.message

      result

  subscribe: (db, queryObject, timeout, callback) ->
    check db, String

    timeout = timeout or Meteor.settings.influx.default_observe_interval
    check timeout, Number

    # Заглушка для дев-режима
    if Meteor.settings.public.stub_metrics and queryObject.fakeData
      interval = Meteor.setInterval ->
        callback null, if _.isFunction queryObject.fakeData then queryObject.fakeData() else queryObject.fakeData
      , timeout

      stop: -> Meteor.clearInterval interval
    # Настоящий запрос за данными
    else
      shouldContinue = true

      repeatedRequest = (last_timestamp) ->
        if shouldContinue
          repeatedQuery = _.extend {}, queryObject
          repeatedQuery.fill = false
          # Какая-то шняга для лога объектов: if not options.preserveWhere
          # repeatedQuery.where = if _.isFunction call_options.where then call_options.where() else call_options.where
          repeatedQuery.where = _.reject repeatedQuery.where, (condition) -> condition.field == 'time'
          repeatedQuery.where.push
            field: 'time'
            function: '>'
            value: "'" + influxDb.timeFormat(last_timestamp) + "' + " + queryObject.resolution

          influxDb.select db, repeatedQuery, (err, result) ->

            time_index = if result?.data?.length then result.data[0].columns.indexOf('time') else false
            callback err, result

            next_timestamp = if result?.data?.length then moment(result.data[0].points[0][time_index] + 1) else last_timestamp

            Meteor.setTimeout ->
              repeatedRequest next_timestamp
            , if not err then timeout else 60000

      repeatedRequest moment(queryObject.lastPoint) or moment()

      stop: -> shouldContinue = false

  insert: (db, table, columns, points) ->
    check db, String
    check table, String
    check columns, Array
    check points, Array

    HTTP.post @dbURL(db),
      timeout: Meteor.settings.influx.timeout
      params: @defaultParams
      data: [ {name: table, columns: columns, points: points} ]
