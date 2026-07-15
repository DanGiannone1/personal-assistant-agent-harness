targetScope = 'resourceGroup'

param accountName string
param runtimePrincipalId string

var openAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource account 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: accountName
}

resource runtimeOpenAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(account.id, 'csa-workbench-runtime-identity', openAiUserRoleId)
  scope: account
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUserRoleId)
    principalId: runtimePrincipalId
    principalType: 'ServicePrincipal'
  }
}
