########################################################################################################################
#
#   Публикация данных всех объектов.
#
########################################################################################################################

Meteor.startup ->
  for model of Models
    do (model) ->
      Meteor.publish Models[model]._namespace + "s", (options) ->
        @unblock()

        publisher = @

        unless options?.fullObjects
          # Реальная подписка с клиента. Задача: в added вместо реальной отправки сообщения делать только то что нужно
          # сделать на сервере, чтобы потом работали changed/removed (надо посмотреть что происходит при отправке)

          init = true
          cursor = Models[model]._matching _global_namespace + ":" + Models[model]._namespace + ':*'
          watcher = cursor.observeChanges
            'added': (id, fields) ->
              if not init
                publisher.added "redis", id, fields
              else
                publisher.added "redis", id, {}
            'removed': (id) ->
              publisher.removed "redis", id
            'changed': (id, fields) ->
              publisher.changed "redis", id, fields

          init = false
          publisher.ready()

          publisher.onStop ->
            watcher.stop()
        else
          # Ненастоящая подписка от Fast Render или же реконнект
          Models[model]._matching _global_namespace + ":" + Models[model]._namespace + ':*'
