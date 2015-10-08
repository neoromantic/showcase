########################################################################################################################
#
#   Методы, связанные с получением данных от метрик
#
########################################################################################################################

Future = Meteor.npmRequire 'fibers/future'

Meteor.methods

  # Получаем значения метрик из influxDB, возвращаем их все вместе
  metricData: (options) ->
    if not @userId
      throw new Meteor.Error(403)

    check options, Match.ObjectIncluding
      metric_ids: Match.Where (x) ->
        check x, [String]
        x.length > 0

    @unblock()

    defaults =
      limit: 10
      date_from: false
      date_to: false
      resolution: '1m'
      live: false

    options = _.extend defaults, options

    query =
      where: []
      fill: null#options.fill
      resolution: options.resolution
      limit: options.limit
      group: if options.resolution == 'raw' then false else " time(#{options.resolution})"
      fakeData: ->
        random_points = _.map [0..Math.min(options.limit, 500)], (i) -> [moment().subtract(minutes: i).unix() * 1000, _.random(0,1000)]
        data: [columns: ['time','value'], points: random_points]

    if options.date_from
      query.where.push
        field: 'time'
        function: '>'
        value: "'" + influxDb.timeFormat(moment(options.date_from)) + "' " +
                    if options.resolution == 'raw' then " + 1s" else " + #{options.resolution}"

    if options.date_to
      query.where.push
        field: "time"
        function: "<"
        value: "'" + influxDb.timeFormat(moment(options.date_to)) + "' "

    metrics = _.compact _.map options.metric_ids, (mid) -> Models.Metric.findOne mid

    futures = _.map metrics, (metric) ->
      fut = new Future()

      parsePoints = (result) ->
        time_index = _.indexOf result.data[0].columns, 'time'
        value_index = _.indexOf result.data[0].columns, 'value'

        metric: metric.id
        points: _.map result.data[0].points, (point) ->
          time: point[time_index]
          value: point[value_index]

      query.series = "metric-#{metric.id}.raw"
      query.columns = ['time', if query.group then "#{metric.aggregate}(value) as value" else 'value']

      influxDb.select 'robonect-metrics', query, (err, result) ->
        if err
          fut.resolver() false, []
        else
          try
            data = parsePoints(result)
            fut.resolver() null, data
          catch err
            fut.resolver() err, null

          query.lastPoint = data.points[0].time
          query.fakeData = -> data: [columns: query.columns, points: [[moment().unix() * 1000, _.random(0,1000)]]]

          if result.data.length and options.live
            handle = influxDb.subscribe 'robonect-metrics', query, options.live.timeout, (err, result) ->
              if not err and result.data.length and result.data[0].points.length
                liveDataStream.emit options.live.channel, [parsePoints(result)]

            liveDataStream.on 'stop' + options.live.channel, -> handle.stop()

      fut

    Future.wait futures
    _.invoke futures, 'get'

  # Возвращает перечень последнего значения для всех метрик, который мы храним в Redis
  metricLastValues: ->
    if not @userId
      throw new Meteor.Error(403)
    fut = new Future()
    redisConnection.hgetall "robonect:metrics-last_values", (err, reply) ->
      if reply
        _.each _.keys(reply), (key) ->
          try
            reply[key] = EJSON.parse reply[key]
          catch err
            reply[key] = {}
        fut['return'] reply
      else
        fut['return'] {}
    fut.wait()
