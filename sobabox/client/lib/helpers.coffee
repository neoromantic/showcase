pluralize = (count, single, several, many) ->
  if count == 1 or (count % 10 == 1 and count > 20)
    single
  else if (count % 10 in [2,3,4] and (count < 10 or count > 20)) or (not many)
    several
  else
    many

Template.registerHelper name, method for name, method of {
  # Очеловечивание
  __: pluralize
  _: (count, single, several, many) -> count + " " + pluralize(count, single, several, many)
}
