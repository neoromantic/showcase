SB.Dictionaries.DogSizes = _.create Dictionary,
  name: 'Размеры собак'
  content:
    S:
      title: 'Маленькие, до 15 кг'
      shortTitle: "до 15 кг"
      maxWeight: 15
    M:
      title: 'Средние, 15-30 кг'
      shortTitle: "15-30 кг"
      maxWeight: 30
    L:
      title:
        'Большие, от 30 кг'
      shortTitle: "от 30 кг"

  getByWeight: (weight) ->
    for key, value of @content
      if not value.maxWeight or value.maxWeight >= weight then return _.extend {key: key}, value
