SB.Dictionaries.DogSexes = _.create Dictionary,
	name: "Собачьи полы"

	content:
		male:
			title: "Кобель"
			plural: "Кобели"

		female:
			title: "Сука"
			plural: "Суки"

	only: (obj) -> "Только " + obj.plural.toLowerCase()
