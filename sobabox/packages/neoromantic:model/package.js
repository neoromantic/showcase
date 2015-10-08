Package.describe({
  name: 'neoromantic:model',
  summary: 'Lightweight models for Meteor',
  version: '1.0.0',
  git: ' /* Fill me in! */ '
});

Package.onUse(function(api) {
  api.versionsFrom('1.0');

  api.use(["coffeescript"]);
  api.addFiles(['model.coffee', 'global_variables.js']);

  api.export("Model", ["client", "server"])

});

Package.onTest(function(api) {
  api.use('tinytest');
  api.use('neoromantic:model');
  api.addFiles('tests.js');
});
